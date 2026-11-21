// Reflect joint targets across the sagittal plane: FL/FR and BL/BR swap.
// Abduction changes sign; hip and knee flexion keep their signs.
export function mirrorJointAngles(angles) {
  return [1, 0, 3, 2].flatMap(leg => [-angles[leg*3], angles[leg*3+1], angles[leg*3+2]]);
}
