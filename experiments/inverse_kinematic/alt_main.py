import numpy as np
import matplotlib.pyplot as plt
from ipywidgets import interact, FloatSlider

# Длины сегментов
L_hip = 10  # длина бедра
L_leg = 10.255  # длина голени
L_caromyslo = 3.191  # длина каромысла голени
L_caromyslo_angle = np.pi - np.deg2rad(32.2)
L_tyaga = 10  # длина тяги голени
L_side_A = 2.4  # длина стороны A качалки (бывший рычаг двигателя 3)
L_side_B = 2.7  # длина стороны B качалки (бывший фантомный рычаг)
L_side_C_angle = 90  # угол в градусах
L_mala_tyaga = 2.8  # длина малой тяги
L_richag_3 = 2.4  # длина нового рычага двигателя 3

# Смещение оси рычага двигателя 3
offset_3_x = 2
offset_3_y = -2

# Ограничения по углам (в радианах)
theta_hip_min = np.deg2rad(135)
theta_hip_max = np.deg2rad(270)
theta_richag_min = np.deg2rad(-45)
theta_richag_max = np.deg2rad(135)
min_theta_dvigatel_3_pos = -70
max_theta_dvigatel_3_pos = 110


# Функция для проверки, находится ли угол в заданном секторе
def in_sector(angle, min_angle, max_angle):
    angle = angle % (2 * np.pi)
    if min_angle < max_angle:
        return min_angle <= angle <= max_angle
    else:
        return min_angle <= angle or angle <= max_angle


# Функция для приведения угла в заданный сектор
def adjust_angle_to_sector(angle, min_angle, max_angle):
    angle = angle % (2 * np.pi)
    if in_sector(angle, min_angle, max_angle):
        return angle
    else:
        delta = (max_angle - min_angle) % (2 * np.pi)
        if angle < min_angle:
            angle += delta
        elif angle > max_angle:
            angle -= delta
        return angle


# Решение уравнений обратной кинематики с учетом ограничений
def inverse_kinematics(target_x, target_y, L_hip, L_leg):
    # Угол голени
    cos_angle_leg = (target_x ** 2 + target_y ** 2 - L_hip ** 2 - L_leg ** 2) / (2 * L_hip * L_leg)
    sin_angle_leg = np.sqrt(1 - cos_angle_leg ** 2)
    theta_leg = np.arctan2(sin_angle_leg, cos_angle_leg)

    # Угол бедра с учетом ограничений
    k1 = L_hip + L_leg * cos_angle_leg
    k2 = L_leg * sin_angle_leg
    theta_hip = np.arctan2(target_y, target_x) - np.arctan2(k2, k1)
    theta_hip = adjust_angle_to_sector(theta_hip, theta_hip_min, theta_hip_max)

    # Угол рычага с учетом ограничений
    theta_richag = np.arctan2(target_y - offset_3_y, target_x - offset_3_x)
    theta_richag = adjust_angle_to_sector(theta_richag, theta_richag_min, theta_richag_max)

    return theta_hip, theta_leg, theta_richag


# Функция для вычисления координат концов рычагов
def calculate_position_richag_3(target_x, target_y, L_dvigatel_3 = L_richag_3, L_malaya_tyaga = L_mala_tyaga):
    # Учет смещения точки вращения
    target_x -= offset_3_x
    target_y -= offset_3_y

    # Уравнения окружностей:
    # (x - 0)^2 + (y - 0)^2 = L_dvigatel_3^2
    # (x - target_x)^2 + (y - target_y)^2 = L_malaya_tyaga^2

    # Найдем пересечения окружностей
    D = np.sqrt(target_x**2 + target_y**2)

    if D > L_dvigatel_3 + L_malaya_tyaga or D < abs(L_dvigatel_3 - L_malaya_tyaga) or (D == 0 and L_dvigatel_3 == L_malaya_tyaga):
        print("Ошибка: нет решений или их бесконечное множество.")
        return None

    a = (L_dvigatel_3**2 - L_malaya_tyaga**2 + D**2) / (2 * D)
    h = np.sqrt(L_dvigatel_3**2 - a**2)

    x2 = a * (target_x) / D
    y2 = a * (target_y) / D

    x3_pos = x2 + h * (target_y) / D
    y3_pos = y2 - h * (target_x) / D

    x3_neg = x2 - h * (target_y) / D
    y3_neg = y2 + h * (target_x) / D

    theta_dvigatel_3_pos = np.arctan2(y3_pos, x3_pos)
    # theta_dvigatel_3_neg = np.arctan2(y3_neg, x3_neg)

    if min_theta_dvigatel_3_pos <= np.degrees(theta_dvigatel_3_pos) <= max_theta_dvigatel_3_pos:
        dvigatel_3_x, dvigatel_3_y, theta_dvigatel_3 = x3_pos, y3_pos, theta_dvigatel_3_pos
    else:
        print("Ошибка: нет решений в заданных угловых пределах.")
        return None

    return (dvigatel_3_x + offset_3_x, dvigatel_3_y + offset_3_y), theta_dvigatel_3


# Вычисление положений точек
def calculate_positions(theta_hip, theta_leg, theta_richag, L_hip, L_leg, L_caromyslo, L_tyaga,
                        L_side_A, L_side_B, phantom_angle):
    # Точка конца бедра (A)
    A_x = L_hip * np.cos(theta_hip)
    A_y = L_hip * np.sin(theta_hip)

    # Точка крепления бедра и голени (B)
    B_x = A_x
    B_y = A_y

    # Точка конца голени (ступня) (E)
    E_x = B_x + L_leg * np.cos(theta_hip + theta_leg)
    E_y = B_y + L_leg * np.sin(theta_hip + theta_leg)

    # Точка конца коромысла (B_ext) с учетом угла и расстояния
    B_ext_x = B_x + L_caromyslo * np.cos(theta_hip + theta_leg + L_caromyslo_angle)
    B_ext_y = B_y + L_caromyslo * np.sin(theta_hip + theta_leg + L_caromyslo_angle)

    # Точка конца тяги (C)
    C_x = B_ext_x + L_tyaga * np.cos(theta_richag)
    C_y = B_ext_y + L_tyaga * np.sin(theta_richag)

    # Перемещаем оси вращения сторон A и B качалки в точку (0, 0)
    # Точка конца стороны A качалки (D) с учетом смещения
    D_x = L_side_A * np.cos(theta_richag)
    D_y = L_side_A * np.sin(theta_richag)

    # Точка конца стороны B качалки (P), угол между рычагами
    phantom_theta_richag = theta_richag - np.deg2rad(phantom_angle)  # угол между рычагами
    P_x = L_side_B * np.cos(phantom_theta_richag)
    P_y = L_side_B * np.sin(phantom_theta_richag)

    # Обновляем конечную точку тяги, соединяя её с концом рычага
    C_x = D_x
    C_y = D_y

    return (0, 0), (A_x, A_y), (B_x, B_y), (B_ext_x, B_ext_y), (C_x, C_y), (D_x, D_y), (P_x, P_y), (E_x, E_y)


def plot_lever_system(target_x, target_y):
    theta_hip, theta_leg, theta_richag = inverse_kinematics(target_x, target_y, L_hip, L_leg)

    if not in_sector(theta_hip, theta_hip_min, theta_hip_max):
        print("Недопустимое решение: Угол бедра выходит за пределы ограничений.")
        return

    if not in_sector(theta_richag, theta_richag_min, theta_richag_max):
        print("Недопустимое решение: Угол рычага выходит за пределы ограничений.")
        return

    origin, A, B, B_ext, C, D, P, E = calculate_positions(
        theta_hip, theta_leg, theta_richag,
        L_hip, L_leg, L_caromyslo, L_tyaga,
        L_side_A, L_side_B, L_side_C_angle
    )

    R, theta_richag_3_deg = calculate_position_richag_3(P[0], P[1], L_richag_3, L_mala_tyaga)

    # Вывод углов в консоль
    print(f"Угол поворота для двигателя 2): {np.degrees(theta_hip):.2f} градусов")
    print(f"Угол поворота для двигателя 3): {np.degrees(theta_richag_3_deg):.2f} градусов")

    plt.figure()
    plt.plot([origin[0], A[0]], [origin[1], A[1]], '-o', color='blue', label='Бедро')
    plt.plot([A[0], E[0]], [A[1], E[1]], '-o', color='green', label='Голень')
    plt.plot([B[0], B_ext[0]], [B[1], B_ext[1]], '-o', color='green', label='Каромысло голени')
    plt.plot([B_ext[0], C[0]], [B_ext[1], C[1]], '-o', color='purple', label='Длинная тяга голени')
    plt.plot([0, D[0]], [0, D[1]], '-o', color='orange', label='Сторона A качалки')
    plt.plot([0, P[0]], [0, P[1]], '-o', color='orange', label='Сторона B качалки')
    plt.plot([D[0], P[0]], [D[1], P[1]], '-o', color='orange', label='Сторона C качалки')
    plt.plot([P[0], R[0]], [P[1], R[1]], '-o', color='cyan', label='Малая тяга')
    plt.plot([offset_3_x, R[0]], [offset_3_y, R[1]], '-o', color='red', label='Рычаг двигателя 3')
    plt.plot(target_x, target_y, 'ro', label='Ступня (целевая точка)')

    plt.xlim(-20, 20)
    plt.ylim(-20, 20)
    plt.axhline(0, color='black', linewidth=0.5)
    plt.axvline(0, color='black', linewidth=0.5)
    plt.grid(color='gray', linestyle='--', linewidth=0.5)
    plt.gca().set_aspect('equal', adjustable='box')
    plt.legend(fontsize=8)  # Уменьшенный размер шрифта легенды
    plt.show()


# Создание ползунков для динамического изменения координат целевой точки
interact(
    plot_lever_system,
    target_x=FloatSlider(min=-15, max=15, step=0.1, value=0),
    target_y=FloatSlider(min=-15, max=5, step=0.1, value=-12)
)