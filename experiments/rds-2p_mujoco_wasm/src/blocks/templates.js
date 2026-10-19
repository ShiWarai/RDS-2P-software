/**
 * Заготовки для вкладки «📦 Шаблоны» — деревья в формате store v3
 * (см. src/rules/store.js). Конвертируются в toolbox-JSON в workspace.js.
 */

const CMD = (command, label) => ({ kind: "command", command, label });
const SAY = (text) => ({ kind: "say", text });

/**
 * Каскад (пример): конкретные команды, а внутри «Дай лапу» — вложенный вопрос-шкала.
 * Никаких абстрактных гейтов: модель надёжно различает только конкретные варианты,
 * у которых в описании свои примеры фраз.
 */
export const CASCADE_EXAMPLE = {
  kind: "start",
  then: [
    {
      kind: "question",
      id: "q_what",
      qtype: "choice",
      name: "Команды",
      instructions: "Какая команда подходит к фразе?",
      options: [
        {
          id: "o_paw",
          name: "Дай лапу",
          examples: ["дай лапу", "лапу", "дай пять"],
          then: [
            {
              kind: "question",
              id: "q_polite",
              qtype: "score",
              name: "Насколько вежливо просят?",
              instructions: "Насколько вежливо ребёнок просит дать лапу?",
              levels: ["грубо требуют", "просто просят", "очень вежливо, с волшебным словом"],
              outcomes: [
                { then: [SAY("Не буду без волшебного слова 🙃")] },
                { then: [CMD("give_paw", "дай лапу")] },
                { then: [CMD("give_paw", "дай лапу"), SAY("С радостью! 🐾")] },
              ],
            },
          ],
        },
        { id: "o_lie", name: "Лежать", examples: ["лежать", "ложись", "ляг"], then: [CMD("lie_down", "лежать")] },
        { id: "o_run", name: "Беги", examples: ["беги", "бег", "побежали"], then: [CMD("step_forward", "шаг вперёд")] },
        { id: "o_stop", name: "Стой", examples: ["стой", "смирно", "остановись"], then: [CMD("stop_running", "стой")] },
      ],
    },
  ],
};

/** Полный набор команд (пресет «Команды Панды»). */
export const COMMANDS_EXAMPLE = {
  kind: "start",
  then: [
    {
      kind: "question",
      id: "q_commands_full",
      qtype: "choice",
      name: "Команды",
      instructions: "Какая команда подходит к фразе?",
      options: [
        { id: "r_paw", name: "Дай лапу", examples: ["дай лапу", "лапу", "поздоровайся", "дай пять"], then: [CMD("give_paw", "дай лапу")] },
        { id: "r_attention", name: "Равняйся", examples: ["равняйся", "стой ровно", "замри"], then: [CMD("stand_at_attention", "равняйся")] },
        { id: "r_dismiss", name: "Отставить", examples: ["отставить", "вставай", "свободен"], then: [CMD("dismiss", "отставить")] },
        { id: "r_lie", name: "Лежать", examples: ["лежать", "ложись", "ляг"], then: [CMD("lie_down", "лежать")] },
        { id: "r_pray", name: "Служить", examples: ["служить", "служи", "поклон"], then: [CMD("pray", "служить")] },
        { id: "r_flip", name: "Кувырок", examples: ["кувырок", "перевернись", "сальто", "вращайся"], then: [CMD("rotate", "кувырок")] },
        { id: "r_run", name: "Беги", examples: ["беги", "бег", "побежали", "пошли"], then: [CMD("step_forward", "шаг вперёд")] },
        { id: "r_stop", name: "Стой", examples: ["смирно", "стоп", "остановись", "хватит бежать"], then: [CMD("stop_running", "стой")] },
        { id: "r_hello", name: "Приветствие", examples: ["привет", "здравствуй", "добрый день"], then: [CMD("stand_at_attention", "равняйся"), { kind: "wait", ms: 600 }, CMD("give_paw", "дай лапу"), SAY("Привет!")] },
        { id: "r_exercise", name: "Зарядка", examples: ["зарядка", "разминка", "сделай зарядку"], then: [CMD("stand_at_attention", "равняйся"), { kind: "wait", ms: 800 }, CMD("give_paw", "дай лапу"), { kind: "wait", ms: 800 }, CMD("dismiss", "отставить")] },
        { id: "r_sleep", name: "Спать", examples: ["спи", "спать", "отбой"], then: [CMD("lie_down", "лежать"), { kind: "wait", ms: 2000 }, CMD("dismiss", "отставить")] },
      ],
    },
  ],
};

/** Шкала с ветвлением по уровням. */
export const SCORE_EXAMPLE = {
  kind: "start",
  then: [
    {
      kind: "question",
      id: "q_how_much_command",
      qtype: "score",
      name: "Насколько это команда?",
      instructions: "Насколько эта фраза — команда роботу?",
      levels: ["низкая", "средняя", "высокая"],
      outcomes: [
        { then: [SAY("Это скорее разговор, а не команда 🤔")] },
        { then: [CMD("stand_at_attention", "равняйся")] },
        { then: [CMD("step_forward", "шаг вперёд")] },
      ],
    },
  ],
};

export const TEMPLATES = [
  { key: "cascade", label: "Каскад (пример)", tree: CASCADE_EXAMPLE },
  { key: "commands", label: "Команды (полный набор)", tree: COMMANDS_EXAMPLE },
  { key: "score", label: "Шкала с ветками", tree: SCORE_EXAMPLE },
];