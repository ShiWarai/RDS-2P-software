#!/usr/bin/env node
/** Дамп деревьев шаблонов (src/blocks/templates.js) в JSON — для tools/check_examples.py. */
import { CASCADE_EXAMPLE, COMMANDS_EXAMPLE, SCORE_EXAMPLE } from "../src/blocks/templates.js";

const trees = {
  cascade: CASCADE_EXAMPLE,
  commands: COMMANDS_EXAMPLE,
  score: SCORE_EXAMPLE,
};
process.stdout.write(JSON.stringify(trees, null, 2));