import { programForCommand } from "../robot/motions.js";
import { PoseManager } from "../sim/poseManager.js";

/**
 * Компилятор «действие → программа движений».
 * action = {type:'chain', steps:[{kind:'command'|'pose'|'wait'|'say', ...}]}
 */
export function compileAction(action, resolvePose) {
  if (!action || action.type !== "chain" || !Array.isArray(action.steps)) {
    return [];
  }
  const out = [];
  for (const step of action.steps) {
    if (step.kind === "command") {
      const prog = programForCommand(step.command);
      if (prog) {
        out.push(...prog);
      } else {
        console.warn("Неизвестная команда пропущена:", step.command);
      }
    } else if (step.kind === "pose") {
      const norm = resolvePose(step.pose);
      out.push({
        kind: "pose",
        pose: norm ?? step.pose,
        blend: step.blend ?? 400,
        hold: step.hold_ms ?? step.hold ?? 500,
        noLimit: norm ? PoseManager.isNoLimit(norm) : false,
        label: `поза «${step.pose}»`,
      });
    } else if (step.kind === "wait") {
      out.push({ kind: "wait", ms: step.ms ?? 500, label: "ждёт" });
    } else if (step.kind === "say") {
      out.push({ kind: "say", text: String(step.text ?? ""), label: `говорит «${step.text ?? ""}»` });
    } else {
      console.warn("Неизвестный шаг действия пропущен:", step.kind);
    }
  }
  return out;
}