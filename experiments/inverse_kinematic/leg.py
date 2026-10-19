import numpy as np

# Длины сегментов
L_leg = 10.255  # длина голени
L_hip = 10      # длина бедра
L_caromyslo = 3.191  # длина каромысла голени
L_caromyslo_angle = np.pi - np.deg2rad(32.2)
L_tyaga = 10    # длина длинной тяги голени
L_side_A = 2.4  # длина стороны A качалки
L_side_B = 2.7  # длина стороны B качалки
L_side_C_angle = 90  # угол в градусах
L_mala_tyaga = 2.8  # длина малой тяги
L_richag_3 = 2.4  # длина рычага двигателя 3

# Смещение оси двигателя 3
offset_3_x = 2
offset_3_y = -2

def circle_intersection(x1, y1, r1, x2, y2, r2):
    """
    Вычисляет точки пересечения двух окружностей.
    Возвращает список точек [(x, y), ...] или None, если пересечений нет.
    """
    d = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    if d > r1 + r2 + 1e-6 or d < abs(r1 - r2) - 1e-6 or (abs(d) < 1e-6 and abs(r1 - r2) < 1e-6):
        return None  # Нет пересечений
    a = (r1**2 - r2**2 + d**2) / (2 * d)
    h = np.sqrt(max(0, r1**2 - a**2))
    xm = x1 + a * (x2 - x1) / d
    ym = y1 + a * (y2 - y1) / d
    if h < 1e-6:
        return [(xm, ym)]  # Одна точка (касание)
    x3 = xm + h * (y2 - y1) / d
    y3 = ym - h * (x2 - x1) / d
    x4 = xm - h * (y2 - y1) / d
    y4 = ym + h * (x2 - x1) / d
    return [(x3, y3), (x4, y4)]  # Две точки

def compute_motor_angles(target_x, target_y):
    """
    Вычисляет углы двигателей на основе целевых координат ступни.
    Аргументы:
        target_x (float): Координата X ступни
        target_y (float): Координата Y ступни
    Возвращает:
        tuple: (motor2_angle, motor3_angle) в градусах, или None, если решение невозможно
    """
    # Находим положение колена (K)
    intersections = circle_intersection(0, 0, L_hip, target_x, target_y, L_leg)
    if not intersections:
        return None
    knee = min(intersections, key=lambda p: p[0])  # Точка с меньшим X
    knee_x, knee_y = knee

    # Угол бедра (motor2)
    theta_hip = np.arctan2(knee_y, knee_x)

    # Угол голени
    d = np.sqrt(target_x**2 + target_y**2)
    cos_angle_leg = (d**2 - L_hip**2 - L_leg**2) / (2 * L_hip * L_leg)
    if abs(cos_angle_leg) > 1:
        return None
    theta_leg = np.arccos(cos_angle_leg)  # Угол всегда положительный

    # Конец каромысла (B_ext)
    B_ext_x = knee_x + L_caromyslo * np.cos(theta_hip + theta_leg + L_caromyslo_angle)
    B_ext_y = knee_y + L_caromyslo * np.sin(theta_hip + theta_leg + L_caromyslo_angle)

    # Точка D (конец стороны A качалки)
    intersections = circle_intersection(0, 0, L_side_A, B_ext_x, B_ext_y, L_tyaga)
    if not intersections:
        return None
    D = max(intersections, key=lambda p: p[1])  # Точка с большим Y
    D_x, D_y = D

    # Точка P (конец стороны B качалки)
    alpha = np.arctan2(D_y, D_x)
    beta = alpha - np.deg2rad(L_side_C_angle)
    P_x = L_side_B * np.cos(beta)
    P_y = L_side_B * np.sin(beta)

    # Точка R (конец рычага двигателя 3)
    intersections = circle_intersection(offset_3_x, offset_3_y, L_richag_3, P_x, P_y, L_mala_tyaga)
    if not intersections:
        return None
    R = max(intersections, key=lambda p: p[0])  # Точка с большим X
    R_x, R_y = R

    # Угол двигателя 3
    theta_dvigatel_3 = np.arctan2(R_y - offset_3_y, R_x - offset_3_x)

    return (np.degrees(theta_hip + 2 * np.pi), np.degrees(theta_dvigatel_3))

def circle_intersection_full(x1, y1, r1, x2, y2, r2):
    """
    Обёртка для circle_intersection для совместимости.
    Возвращает список точек или None.
    """
    return circle_intersection(x1, y1, r1, x2, y2, r2)

def inverse_kinematics(target_x, target_y):
    """
    Выполняет обратную кинематику.
    Аргументы:
        target_x (float): Координата X ступни
        target_y (float): Координата Y ступни
    Возвращает:
        dict: Углы двигателей и позиции точек, или строка с ошибкой
    """
    result = compute_motor_angles(target_x, target_y)
    if not result:
        return "Ошибка: Невозможно вычислить углы (нет пересечений или некорректная конфигурация)."

    motor2_angle, motor3_angle = result

    # Позиции для визуализации
    knee = min(circle_intersection(0, 0, L_hip, target_x, target_y, L_leg), key=lambda p: p[0])
    knee_x, knee_y = knee
    theta_hip = np.arctan2(knee_y, knee_x)
    theta_leg = np.arccos((target_x**2 + target_y**2 - L_hip**2 - L_leg**2) / (2 * L_hip * L_leg))
    B_ext_x = knee_x + L_caromyslo * np.cos(theta_hip + theta_leg + L_caromyslo_angle)
    B_ext_y = knee_y + L_caromyslo * np.sin(theta_hip + theta_leg + L_caromyslo_angle)
    D = max(circle_intersection(0, 0, L_side_A, B_ext_x, B_ext_y, L_tyaga), key=lambda p: p[1])
    D_x, D_y = D
    alpha = np.arctan2(D_y, D_x)
    beta = alpha - np.deg2rad(L_side_C_angle)
    P_x = L_side_B * np.cos(beta)
    P_y = L_side_B * np.sin(beta)
    R = max(circle_intersection(offset_3_x, offset_3_y, L_richag_3, P_x, P_y, L_mala_tyaga), key=lambda p: p[0])
    R_x, R_y = R

    return {
        "motor2_angle": motor2_angle,
        "motor3_angle": motor3_angle,
        "positions": {
            "origin": (0, 0),
            "knee": (knee_x, knee_y),
            "B_ext": (B_ext_x, B_ext_y),
            "D": (D_x, D_y),
            "P": (P_x, P_y),
            "R": (R_x, R_y),
            "foot": (target_x, target_y)
        }
    }

def compute_angle_between_hip_and_shin(theta2_deg, theta3_deg):
    """
    Вычисляет угол между бедром и голенью.
    Аргументы:
        theta2_deg (float): Угол двигателя 2 в градусах
        theta3_deg (float): Угол двигателя 3 в градусах
    Возвращает:
        float: Угол в градусах, или None, если решение невозможно
    """
    theta2 = np.deg2rad(theta2_deg + 180)
    theta3 = np.deg2rad(theta3_deg)

    K_x = L_hip * np.cos(theta2)
    K_y = L_hip * np.sin(theta2)
    R_x = offset_3_x + L_richag_3 * np.cos(theta3)
    R_y = offset_3_y + L_richag_3 * np.sin(theta3)

    intersections = circle_intersection(0, 0, L_side_B, R_x, R_y, L_mala_tyaga)
    if not intersections:
        return None
    P = max(intersections, key=lambda p: p[1])
    P_x, P_y = P

    alpha = np.arctan2(P_y, P_x) + np.deg2rad(L_side_C_angle)
    D_x = L_side_A * np.cos(alpha)
    D_y = L_side_A * np.sin(alpha)

    intersections = PARKOURcircle_intersection(D_x, D_y, L_tyaga, K_x, K_y, L_caromyslo)
    if not intersections:
        return None
    B_ext = max(intersections, key=lambda p: p[1])
    B_ext_x, B_ext_y = B_ext

    psi = np.arctan2(B_ext_y - K_y, B_ext_x - K_x)
    theta_leg = (psi - theta2 - L_caromyslo_angle) % (2 * np.pi)
    return 180 - np.degrees(theta_leg)

def direct_kinematics(theta2_deg, theta3_deg):
    """
    Вычисляет прямую кинематику.
    Аргументы:
        theta2_deg (float): Угол двигателя 2 в градусах
        theta3_deg (float): Угол двигателя 3 в градусах
    Возвращает:
        dict: Угол между бедром и голенью, позиции точек и предупреждения
    """
    warnings = []
    theta2 = np.deg2rad(theta2_deg + 180)
    theta3 = np.deg2rad(theta3_deg)

    K_x = L_hip * np.cos(theta2)
    K_y = L_hip * np.sin(theta2)
    R_x = offset_3_x + L_richag_3 * np.cos(theta3)
    R_y = offset_3_y + L_richag_3 * np.sin(theta3)

    intersections = circle_intersection(0, 0, L_side_B, R_x, R_y, L_mala_tyaga)
    if not intersections:
        return "Ошибка: Нет пересечений для точки P."
    P = max(intersections, key=lambda p: p[1]) if len(intersections) > 1 else intersections[0]
    P_x, P_y = P
    if len(intersections) == 1:
        warnings.append("Предупреждение: Одно пересечение для точки P.")

    alpha = np.arctan2(P_y, P_x) + np.deg2rad(L_side_C_angle)
    D_x = L_side_A * np.cos(alpha)
    D_y = L_side_A * np.sin(alpha)

    intersections = circle_intersection(D_x, D_y, L_tyaga, K_x, K_y, L_caromyslo)
    if not intersections:
        return "Ошибка: Нет пересечений для точки B_ext."
    B_ext = min(intersections, key=lambda p: abs((180 - np.degrees((np.arctan2(p[1] - K_y, p[0] - K_x) - theta2 - L_caromyslo_angle) % (2 * np.pi)))))
    B_ext_x, B_ext_y = B_ext
    if len(intersections) == 1:
        warnings.append("Предупреждение: Одно пересечение для точки B_ext.")

    theta_leg = (np.arctan2(B_ext_y - K_y, B_ext_x - K_x) - theta2 - L_caromyslo_angle) % (2 * np.pi)
    knee_angle_deg = (180 - np.degrees(theta_leg)) % 360
    if knee_angle_deg < 0:
        warnings.append(f"Предупреждение: Угол между бедром и голенью отрицательный ({knee_angle_deg:.2f}°).")

    F_x = K_x + L_leg * np.cos(theta2 + theta_leg)
    F_y = K_y + L_leg * np.sin(theta2 + theta_leg)

    return {
        "angle_between_hip_and_shin": knee_angle_deg,
        "motor2_angle": theta2_deg,
        "motor3_angle": theta3_deg,
        "positions": {
            "origin": (0, 0),
            "knee": (K_x, K_y),
            "B_ext": (B_ext_x, B_ext_y),
            "D": (D_x, D_y),
            "P": (P_x, P_y),
            "R": (R_x, R_y),
            "foot": (F_x, F_y)
        },
        "warnings": warnings
    }