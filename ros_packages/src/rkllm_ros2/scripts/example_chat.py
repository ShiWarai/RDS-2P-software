#!/usr/bin/env python3
"""Клиент ChatCompletion для rkllm_ros2 (пример: только текст).

  Интерактивно (по умолчанию как stdin multimodal demo при persist_session_kv:=true на ноде):
    ros2 run rkllm_ros2 example_chat.py
    Одна строка = один prompt, KV накапливается на стороне RKLLM (goal.keep_history не отключает KV при persist).

  Legacy — история целиком в каждом user_message + keep_history=false (совместимо с persist_session_kv:=false):
    ros2 run rkllm_ros2 example_chat.py --replay

  Один запрос из argv:
    ros2 run rkllm_ros2 example_chat.py "Переведи: добрый день"

  Multimodal (картинка): см. example_vision.py.

  Требуется: ros2 launch rkllm_ros2 rkllm.launch.py ...
"""

from __future__ import annotations

import argparse
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from rkllm_ros2.action import ChatCompletion


def _try_clear_kv(node: Node, action_name: str) -> None:
    """Сброс KV на ноде: начало новой CLI-сессии без наследия контекста прошлого клиента."""
    from std_srvs.srv import Trigger

    base = action_name.rpartition('/')[0]
    srv_name = base + '/clear_kv_cache'
    cli = node.create_client(Trigger, srv_name)
    if not cli.wait_for_service(timeout_sec=5.0):
        node.get_logger().warn(
            f'{srv_name} недоступен — возможно смешение KV с предыдущих клиентов'
        )
        return
    fut = cli.call_async(Trigger.Request())
    rclpy.spin_until_future_complete(node, fut)
    res = fut.result()
    if res is None or not res.success:
        msg = res.message if res else 'нет ответа'
        node.get_logger().warn(f'clear_kv_cache: {msg}')


def _send_goal(
    node: Node,
    client: ActionClient,
    *,
    user_message: str,
    keep_history: bool,
) -> tuple[bool, str]:
    goal = ChatCompletion.Goal()
    goal.user_message = user_message
    goal.keep_history = keep_history
    goal.max_new_tokens = 0

    def feedback_cb(msg):
        t = msg.feedback.token
        if t:
            print(t, end='', flush=True)

    send_future = client.send_goal_async(goal, feedback_callback=feedback_cb)
    rclpy.spin_until_future_complete(node, send_future)
    gh = send_future.result()
    if not gh.accepted:
        print('\n[цель отклонена — нода занята?]', file=sys.stderr)
        return False, ''

    result_future = gh.get_result_async()
    rclpy.spin_until_future_complete(node, result_future)
    res = result_future.result().result
    print()
    if not res.success:
        node.get_logger().error(res.message)
        return False, res.text
    return True, res.text


def _render_history_prompt(history: list[tuple[str, str]], user_text: str) -> str:
    """Собрать один user_message с полной историей (--replay / legacy).

    Без мета-инструкций вроде «отвечай только на последнюю реплику» — на части моделей
    это провоцирует сломанный ответ (рассуждения о формате диалога вместо текста).
    """
    parts: list[str] = []
    for user_turn, assistant_turn in history:
        parts.append(f'Пользователь: {user_turn}')
        parts.append(f'Ассистент: {assistant_turn}')
    parts.append(f'Пользователь: {user_text}')
    parts.append('Ассистент:')
    return '\n'.join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'message',
        nargs='*',
        help='Текст запроса; если пусто — интерактивный режим',
    )
    parser.add_argument(
        '--action',
        default='/rkllm_ros2/complete',
        help='Имя action-сервера',
    )
    parser.add_argument(
        '--replay',
        action='store_true',
        help='Legacy: весь диалог в каждом user_message + keep_history=false '
        '(ожидается persist_session_kv:=false на ноде; иначе двойной контекст)',
    )
    parser.add_argument(
        '--no-history',
        action='store_true',
        help='Изолировать запросы: перед goal вызывается clear_kv_cache '
        'и передаётся keep_history=false (интерактив — перед каждой репликой)',
    )
    parser.add_argument(
        '--no-clear-start',
        action='store_true',
        help='Не вызывать clear_kv_cache перед чатом (оставить KV от других клиентов)',
    )
    args = parser.parse_args()

    if args.replay and args.no_history:
        parser.error('нельзя одновременно --replay и --no-history')

    one_shot_text = ' '.join(args.message).strip()
    one_shot = bool(one_shot_text)

    rclpy.init()
    node = Node('rkllm_example_chat')
    client = ActionClient(node, ChatCompletion, args.action)

    try:
        if not client.wait_for_server(timeout_sec=30.0):
            node.get_logger().error(f'нет сервера {args.action} (запущен ли rkllm_node?)')
            sys.exit(1)

        if one_shot:
            if args.no_history:
                _try_clear_kv(node, args.action)
            keep = not args.no_history
            print('Ответ: ', end='', flush=True)
            ok, _ = _send_goal(
                node,
                client,
                user_message=one_shot_text,
                keep_history=keep,
            )
            sys.exit(0 if ok else 1)

        print('Чат (ChatCompletion). exit / quit / Ctrl+D — выход.')
        if args.no_history:
            print(
                'Режим: перед каждой репликой — ~/clear_kv_cache и keep_history=false.\n'
            )
        elif args.replay:
            print(
                'Режим --replay: история в тексте каждого goal и keep_history=false. '
                'При persist_session_kv:=true на ноде контекст дублируется с KV — '
                'лучше запускать ноду с persist_session_kv:=false.\n'
            )
        else:
            print(
                'Режим по умолчанию: одна строка = один prompt, keep_history=true; '
                'KV копится в RKLLM (как локальный multimodal demo). Новая сессия — '
                'clear_kv_cache при старте (см. --no-clear-start).\n'
            )

        if not args.no_clear_start:
            _try_clear_kv(node, args.action)

        history: list[tuple[str, str]] = []
        while rclpy.ok():
            try:
                line = input('Вы: ').strip()
            except EOFError:
                print()
                break
            if not line:
                continue
            if line.lower() in ('exit', 'quit'):
                break

            if args.no_history:
                _try_clear_kv(node, args.action)
                prompt = line
                keep_kv = False
            elif args.replay:
                prompt = _render_history_prompt(history, line)
                keep_kv = False
            else:
                prompt = line
                keep_kv = True

            print('Бот: ', end='', flush=True)
            ok, assistant_text = _send_goal(
                node,
                client,
                user_message=prompt,
                keep_history=keep_kv,
            )
            if not ok:
                continue
            if args.replay:
                history.append((line, assistant_text.strip()))

    except KeyboardInterrupt:
        print('\n[прервано]')
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
