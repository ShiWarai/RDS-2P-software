#!/usr/bin/env python3
"""LLM-прослойка: STT-транскрипции → классификация (system-one) → команда или диалог.

Схема:

  /audio/transcription (vosk_ros2/Transcription)
        → choice-классификатор /system_one/systemone (kev-0.8b, критерии classifier_json)
        ├─ метка из classifier.actions:
        │    объявление classifier.say через Paroli /speak (например «Встаю!»),
        │    затем каноническая фраза в command_topic (/audio/command_transcription)
        │    — её принимает command_parser (commands_system) при запуске с
        │    transcription_topics:=['/audio/command_transcription']
        └─ иначе («разговор») → rkllm ChatCompletion + озвучка Paroli
             (см. llm_commands.LlmCommands).

Пока робот генерирует или говорит (диалог либо объявление команды) транскрипции
отбрасываются — без AEC робот не должен слышать сам себя. Пропускается только
dialog_interrupt_keywords («стоп»): прерывает диалог; если прерывается объявление,
ещё не отправленная команда отменяется. После конца озвучки действует
post_speech_cooldown_sec — окно, гасящее хвост собственного эха.
"""

from __future__ import annotations

import json
import re
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from vosk_ros2.msg import Transcription
from rkllm_ros2_msgs.srv import SystemOne
from paroli_ros2.srv import Speak

from rds_2p_commands.llm_commands import LlmCommands

DEFAULT_CLASSIFIER = {
    'instructions': 'Выбери команду робота, которой соответствует текст.',
    'criteria': {
        'dismiss': 'отставить, встань, вставай, отбой',
        'lie_down': 'лежать, ложись, ляг',
        'stand_at_attention': 'равняйся, выровняйся, равняйсь',
        'unknown': (
            'не команда: вопрос, болтовня, похвала; отрицание или сомнение '
            '(не лежать, не беги, не давай лапу)'
        ),
    },
    'actions': {
        'dismiss': 'вставай',
        'lie_down': 'ложись',
        'stand_at_attention': 'равняйсь',
    },
    'say': {
        'dismiss': 'Встаю!',
        'lie_down': 'Ложусь!',
        'stand_at_attention': 'Равняюсь!',
    },
}

PANDA_SYSTEM_PROMPT = (
    'Ты робот-панда, отвечай на вопросы гостей. '
    'На вопросы отвечай кратко. '
    'Не придумывай точную информацию. '
    'У тебя есть зрение с помощью камеры, фото с которой будет передаваться '
    'при надобности тебе.'
)


class LlmLayerNode(Node):
    """Маршрутизатор: команда → Paroli-объявление + command_topic, разговор → LLM+TTS."""

    def __init__(self) -> None:
        super().__init__('llm_layer')

        self.declare_parameter('input_topic', '/audio/transcription')
        self.declare_parameter('command_topic', '/audio/command_transcription')
        self.declare_parameter('system_one_service', '/system_one/systemone')
        self.declare_parameter('system_one_model', 'kev-0.8b')
        self.declare_parameter('classifier_json', json.dumps(DEFAULT_CLASSIFIER, ensure_ascii=False))
        self.declare_parameter('min_confidence', 0.0)
        self.declare_parameter('dialog_interrupt_keywords', ['стоп'])
        self.declare_parameter('announce_commands', True)
        self.declare_parameter('announce_timeout_sec', 10.0)
        self.declare_parameter('post_speech_cooldown_sec', 2.5)
        self.declare_parameter('camera_topic', '/camera/color/image_raw')
        self.declare_parameter('camera_stale_sec', 2.0)
        self.declare_parameter('look_trigger_substrings', ['смотри', 'глянь', 'гляни', 'видишь', 'видно'])
        self.declare_parameter('llm_system_prompt', PANDA_SYSTEM_PROMPT)

        # Параметры, которые читает LlmCommands (те же имена, что у command_parser).
        self.declare_parameter('rkllm_complete_action', '/rkllm_ros2/complete')
        self.declare_parameter('rkllm_clear_kv_service', '/rkllm_ros2/clear_kv_cache')
        self.declare_parameter('paroli_speak_service', '/paroli_ros2/speak')
        self.declare_parameter('paroli_stop_speech_service', '/paroli_ros2/stop_speech')
        self.declare_parameter('rkllm_wait_server_sec', 5.0)
        self.declare_parameter('paroli_wait_service_sec', 3.0)
        self.declare_parameter('rkllm_keep_history', True)
        self.declare_parameter('rkllm_clear_kv_before_query', False)
        self.declare_parameter('rkllm_max_new_tokens', 0)
        self.declare_parameter('llm_stream_tts_by_punctuation', True)
        self.declare_parameter('llm_sanitize_user_and_reply', True)
        self.declare_parameter('llm_stream_min_chunk_chars', 2)
        self.declare_parameter('llm_reply_log_max_chars', 280)
        self.declare_parameter('paroli_speak_log_max_chars', 0)
        self.declare_parameter('panda_llm_tts_enabled', True)
        self.declare_parameter('panda_llm_trigger_substring', 'панда')

        self._input_topic = self._str_param('input_topic')
        self._command_topic = self._str_param('command_topic')
        self._system_one_model = self._str_param('system_one_model')
        self._min_confidence = self.get_parameter('min_confidence').get_parameter_value().double_value
        self._talk_enabled = (
            self.get_parameter('panda_llm_tts_enabled').get_parameter_value().bool_value
        )
        self._announce_enabled = (
            self.get_parameter('announce_commands').get_parameter_value().bool_value
        )
        self._announce_timeout_sec = (
            self.get_parameter('announce_timeout_sec').get_parameter_value().double_value
        )
        self._post_speech_cooldown_sec = (
            self.get_parameter('post_speech_cooldown_sec').get_parameter_value().double_value
        )
        self._camera_stale_sec = (
            self.get_parameter('camera_stale_sec').get_parameter_value().double_value
        )
        self._look_triggers = [
            str(t).strip().lower()
            for t in self.get_parameter('look_trigger_substrings').get_parameter_value().string_array_value
            if str(t).strip()
        ]
        self._interrupt_keywords = [
            str(k).strip().lower()
            for k in self.get_parameter('dialog_interrupt_keywords').get_parameter_value().string_array_value
            if str(k).strip()
        ]

        self._classifier = self._load_classifier()
        self._labels = list(self._classifier['criteria'])
        self._actions = dict(self._classifier['actions'])
        self._say = dict(self._classifier['say']) if self._announce_enabled else {}

        self._llm = LlmCommands(self)
        self._classify_inflight = False

        self._speak_client = None
        paroli_name = self._str_param('paroli_speak_service')
        if paroli_name and self._announce_enabled:
            self._speak_client = self.create_client(Speak, paroli_name)

        # Блокировка «не слушаем себя» на время объявления команды.
        self._speak_guard = False
        self._guard_timer = None
        self._announce_seq = 0
        self._announce_token = None
        # Окно после конца любой озвучки (диалога) — хвост эха.
        self._was_busy = False
        self._last_speech_end = None
        self.create_timer(0.25, self._watch_busy)

        self._command_pub = self.create_publisher(Transcription, self._command_topic, 10)
        self.create_subscription(Transcription, self._input_topic, self._on_transcription, 10)
        self._system_one_client = self.create_client(
            SystemOne, self._str_param('system_one_service'))

        # Камера: кэшируем последний кадр для команды «посмотри».
        self._last_image: Image | None = None
        self._last_image_at = 0.0
        self.create_subscription(
            Image, self._str_param('camera_topic'), self._on_camera_image, 10)

        sys_prompt = (
            self.get_parameter('llm_system_prompt').get_parameter_value().string_value or ''
        ).strip()
        self.get_logger().info(
            f'llm_layer готов: {self._input_topic} → [{", ".join(self._labels)}]; '
            f'команды в {self._command_topic}, разговор → {self._str_param("rkllm_complete_action")} '
            f'+ Paroli; объявления команд: {"вкл" if self._say else "выкл"}; '
            f'прерывание: {self._interrupt_keywords}; '
            f'зрение: {self._look_triggers} (камера {self._str_param("camera_topic")}); '
            f'system prompt: {"вкл" if sys_prompt else "выкл"}'
        )
        if not self._talk_enabled:
            self.get_logger().warn('panda_llm_tts_enabled=false — разговорная ветка выключена')
        self._llm.log_startup_summary()

    # ---- параметры/конфиг -------------------------------------------------

    def _str_param(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value.strip()

    def _load_classifier(self) -> dict:
        raw = self.get_parameter('classifier_json').get_parameter_value().string_value
        try:
            cfg = json.loads(raw) if raw.strip() else dict(DEFAULT_CLASSIFIER)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f'classifier_json: невалидный JSON ({exc}) — беру дефолт')
            cfg = dict(DEFAULT_CLASSIFIER)
        criteria = cfg.get('criteria') or {}
        actions = cfg.get('actions') or {}
        if not isinstance(criteria, dict) or not criteria:
            self.get_logger().error('classifier_json: пустой criteria — беру дефолт')
            cfg = dict(DEFAULT_CLASSIFIER)
            criteria, actions = cfg['criteria'], cfg['actions']
        bad = [label for label in actions if label not in criteria]
        if bad:
            self.get_logger().warn(f'classifier_json: actions без criteria: {bad} — игнорирую их')
            actions = {k: v for k, v in actions.items() if k in criteria}
        say = {str(k): str(v) for k, v in (cfg.get('say') or {}).items() if str(v).strip()}
        return {
            'instructions': str(cfg.get('instructions') or DEFAULT_CLASSIFIER['instructions']),
            'criteria': {str(k): str(v) for k, v in criteria.items()},
            'actions': {str(k): str(v) for k, v in actions.items()},
            'say': say,
        }

    # ---- вход ---------------------------------------------------------------

    def _on_transcription(self, msg: Transcription) -> None:
        text = (msg.text or '').strip()
        if not text:
            return
        self.get_logger().info(f'Транскрипт: {text}')

        if self._match_interrupt(text):
            if self._announce_token is not None:
                self._announce_token = None
                self.get_logger().info('Объявление прервано — команда не отправляется')
            self.get_logger().info(f'Прерывание ({text!r}) — стоп диалога/объявления')
            self._llm.handle_interrupt('llm_layer')
            return

        if self._speak_guard:
            self.get_logger().info('Пропуск: робот объявляет команду (себя не слушаем)')
            return

        if self._llm.busy:
            self.get_logger().info('Пропуск: идёт диалог LLM/озвучка (прервать — «стоп»)')
            return

        cooldown = self._post_speech_cooldown_sec
        if (
            cooldown > 0.0
            and self._last_speech_end is not None
            and (time.monotonic() - self._last_speech_end) < cooldown
        ):
            self.get_logger().info(
                f'Пропуск: хвост собственной озвучки (post_speech_cooldown {cooldown:.1f} с)'
            )
            return

        if self._classify_inflight:
            self.get_logger().info('Пропуск: классификация предыдущей фразы ещё идёт')
            return

        if self._look_triggers and any(t in text.lower() for t in self._look_triggers):
            self._dispatch_look(text)
            return

        self._classify(text)

    # ---- классификация -----------------------------------------------------

    def _classify(self, text: str) -> None:
        cli = self._system_one_client
        if not cli.service_is_ready() and not cli.wait_for_service(timeout_sec=0.5):
            self.get_logger().warn(
                'system-one недоступен — фраза пропущена '
                '(контейнер: scripts/system_one_docker.sh run)'
            )
            return

        req = SystemOne.Request()
        req.model = self._system_one_model
        req.type = 'choice'
        req.state = text
        req.instructions = self._classifier['instructions']
        req.labels = self._labels
        req.descriptions = [self._classifier['criteria'][label] for label in self._labels]

        self._classify_inflight = True
        fut = cli.call_async(req)
        fut.add_done_callback(lambda f: self._on_classified(f, text))

    def _on_classified(self, fut, text: str) -> None:
        self._classify_inflight = False
        try:
            resp = fut.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'system-one вызов: {exc}')
            return

        if not resp.success:
            self.get_logger().warn(f'system-one: {resp.message}')
            return

        label = (resp.choice or '').strip()
        conf = float(resp.confidence)
        probs = resp.probabilities_json or '{}'

        if label in self._actions and conf >= self._min_confidence:
            phrase = self._actions[label]
            say = self._say.get(label, '')
            self.get_logger().info(
                f'Команда: {label} → {phrase!r} (conf {conf:.3f}, {resp.latency_ms} ms; {text!r})'
            )
            if say and self._speak_client is not None:
                self._announce_then_command(label, say, phrase)
            else:
                self._publish_command(label, phrase)
            return

        if label in self._actions:
            self.get_logger().info(
                f'Команда {label}: conf {conf:.3f} < min_confidence {self._min_confidence:.3f} '
                '— трактую как разговор'
            )
        else:
            self.get_logger().info(
                f'Разговор ({label}, conf {conf:.3f}, {resp.latency_ms} ms; probs {probs}) → LLM+Paroli'
            )
        self._dispatch_talk(text)

    # ---- объявление команды --------------------------------------------------

    def _announce_then_command(self, label: str, say: str, phrase: str) -> None:
        cli = self._speak_client
        if not cli.service_is_ready() and not cli.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn('Paroli /speak недоступен — команда без объявления')
            self._publish_command(label, phrase)
            return

        self._announce_seq += 1
        token = self._announce_seq
        self._announce_token = token
        self._arm_guard()
        req = Speak.Request()
        req.text = say
        req.volume = 1.5
        self.get_logger().info(f'Объявление перед командой: {say!r}, затем {phrase!r}')
        fut = cli.call_async(req)
        fut.add_done_callback(lambda f: self._on_announced(f, label, phrase, token))

    def _on_announced(self, fut, label: str, phrase: str, token: int) -> None:
        self._clear_guard()
        cancelled = self._announce_token != token
        self._announce_token = None
        try:
            res = fut.result()
            if res is not None and not res.success:
                self.get_logger().warn(f'Paroli speak: {res.message}')
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'Paroli speak: {exc}')
        if cancelled:
            self.get_logger().info('Команда отменена (объявление прервано «стоп»)')
            return
        self._publish_command(label, phrase)

    def _publish_command(self, label: str, phrase: str) -> None:
        out = Transcription()
        out.text = phrase
        self._command_pub.publish(out)
        self.get_logger().info(f'Команда отправлена: {label} → {phrase!r}')

    def _arm_guard(self) -> None:
        self._speak_guard = True
        if self._guard_timer is not None:
            self._guard_timer.cancel()
        self._guard_timer = self.create_timer(self._announce_timeout_sec, self._on_guard_timeout)

    def _clear_guard(self) -> None:
        self._speak_guard = False
        if self._guard_timer is not None:
            self._guard_timer.cancel()
            self._guard_timer = None

    def _on_guard_timeout(self) -> None:
        self.get_logger().warn(
            f'Объявление не завершилось за {self._announce_timeout_sec:.1f} с — снимаю блокировку'
        )
        if self._announce_token is not None:
            self._announce_token = None
            self.get_logger().warn('Команда отменена (таймаут объявления)')
        self._clear_guard()

    def _watch_busy(self) -> None:
        """Фиксируем момент окончания диалога/озвучки — окно post_speech_cooldown_sec."""
        busy = self._llm.busy or self._speak_guard
        if self._was_busy and not busy:
            self._last_speech_end = time.monotonic()
        self._was_busy = busy

    # ---- разговорная ветка --------------------------------------------------

    def _on_camera_image(self, msg: Image) -> None:
        self._last_image = msg
        self._last_image_at = time.monotonic()

    def _dispatch_look(self, text: str) -> None:
        """«посмотри»: последний кадр камеры + текст → мультимодальный запрос к LLM."""
        if not self._talk_enabled:
            self.get_logger().warn('Разговорная ветка выключена (panda_llm_tts_enabled=false)')
            return
        if not self._llm.rkllm_client_ok:
            self.get_logger().warn('rkllm action не сконфигурирован — ответ невозможен')
            return
        image = None
        if (
            self._last_image is not None
            and (time.monotonic() - self._last_image_at) <= self._camera_stale_sec
        ):
            image = self._last_image
        else:
            self.get_logger().warn(
                '«посмотри»: свежего кадра камеры нет — запрос уйдёт без изображения '
                '(камера запущена? ros2 launch rds_2p astra_mini.launch.py)'
            )
        self.get_logger().info(
            f'Зрение: {"с изображением" if image is not None else "без изображения"} '
            f'→ LLM: {text!r}'
        )
        self._llm.dispatch(text, image=image)

    def _dispatch_talk(self, text: str) -> None:
        if not self._talk_enabled:
            self.get_logger().warn('Разговорная ветка выключена (panda_llm_tts_enabled=false)')
            return
        if not self._llm.rkllm_client_ok:
            self.get_logger().warn('rkllm action не сконфигурирован — ответ невозможен')
            return
        self._llm.dispatch(text)

    # ---- прерывание ---------------------------------------------------------

    def _match_interrupt(self, text: str) -> bool:
        tl = (text or '').lower().strip()
        if not tl:
            return False
        tokens = re.findall(r'\w+', tl, flags=re.UNICODE)
        for kw in self._interrupt_keywords:
            raw = (kw or '').strip().lower()
            if not raw:
                continue
            if ' ' in raw:
                if raw in tl:
                    return True
                continue
            for i, tok in enumerate(tokens):
                if tok != raw:
                    continue
                if raw == 'хватит' and i > 0 and tokens[i - 1] == 'не':
                    continue
                return True
        return False


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LlmLayerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()