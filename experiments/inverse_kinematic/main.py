import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# Длины сегментов
L_hip = 10  # длина бедра
L_leg = 10  # длина голени
L_caromyslo = 2  # длина каромысла голени
L_tyaga = 10  # длина тяги голени
L_richag = 2.1  # длина рычага двигателя 3

# Начальные координаты целевой точки (ступня)
target_x = 0
target_y = -10

# Решение уравнений обратной кинематики
def inverse_kinematics(target_x, target_y, L_hip, L_leg):
    # Угол голени
    cos_angle_leg = (target_x ** 2 + target_y ** 2 - L_hip ** 2 - L_leg ** 2) / (2 * L_hip * L_leg)
    sin_angle_leg = np.sqrt(1 - cos_angle_leg ** 2)
    theta_leg = np.arctan2(sin_angle_leg, cos_angle_leg)

    # Угол бедра
    k1 = L_hip + L_leg * cos_angle_leg
    k2 = L_leg * sin_angle_leg
    theta_hip = np.arctan2(target_y, target_x) - np.arctan2(k2, k1)

    # Угол рычага
    theta_richag = np.pi / 3  # начальное значение угла рычага двигателя 3

    return theta_hip, theta_leg, theta_richag

# Вычисление положений точек
def calculate_positions(theta_hip, theta_leg, theta_richag, L_hip, L_leg, L_caromyslo, L_tyaga, L_richag):
    # Точка конца бедра (A)
    A_x = L_hip * np.cos(theta_hip)
    A_y = L_hip * np.sin(theta_hip)

    # Точка крепления бедра и голени (B)
    B_x = A_x
    B_y = A_y

    # Точка конца голени (ступня) (E)
    E_x = B_x + L_leg * np.cos(theta_hip + theta_leg)
    E_y = B_y + L_leg * np.sin(theta_hip + theta_leg)

    # Точка конца каромысла (B_ext)
    B_ext_x = B_x - L_caromyslo * np.cos(theta_hip + theta_leg)
    B_ext_y = B_y - L_caromyslo * np.sin(theta_hip + theta_leg)

    # Точка конца тяги (C)
    C_x = B_ext_x + L_tyaga * np.cos(theta_richag)
    C_y = B_ext_y + L_tyaga * np.sin(theta_richag)

    # Точка конца рычага двигателя 3 (D)
    D_x = L_richag * np.cos(theta_richag)
    D_y = L_richag * np.sin(theta_richag)

    # Обновляем конечную точку тяги, соединяя её с концом рычага
    C_x = D_x
    C_y = D_y

    return (0, 0), (A_x, A_y), (B_x, B_y), (B_ext_x, B_ext_y), (C_x, C_y), (D_x, D_y), (E_x, E_y)

# Функция для обновления анимации
def update(frame):
    global target_x, target_y
    # Обновляем координаты целевой точки (ступни)
    target_x = 5 * np.sin(2 * np.pi * frame / 100)
    target_y = -10 + 5 * np.cos(2 * np.pi * frame / 100)

    # Решение обратной кинематики
    theta_hip, theta_leg, theta_richag = inverse_kinematics(target_x, target_y, L_hip, L_leg)

    # Вычисление положений точек
    origin, A, B, B_ext, C, D, E = calculate_positions(theta_hip, theta_leg, theta_richag, L_hip, L_leg, L_caromyslo, L_tyaga, L_richag)

    # Обновление позиций на графике
    lines[0].set_data([origin[0], A[0]], [origin[1], A[1]])
    lines[1].set_data([A[0], E[0]], [A[1], E[1]])
    lines[2].set_data([B[0], B_ext[0]], [B[1], B_ext[1]])
    lines[3].set_data([B_ext[0], C[0]], [B_ext[1], C[1]])
    lines[4].set_data([origin[0], D[0]], [origin[1], D[1]])
    lines[5].set_data([E[0]], [E[1]])
    lines[6].set_data([target_x], [target_y])

    return lines

# Инициализация графика
fig, ax = plt.subplots()
ax.set_xlim(-L_hip - L_leg - L_caromyslo, L_hip + L_leg + L_caromyslo)
ax.set_ylim(-L_hip - L_leg - L_caromyslo, L_hip + L_leg + L_caromyslo)
ax.set_aspect('equal')

# Инициализация линий для отрисовки
lines = [ax.plot([], [], '-o', color='blue')[0],  # Бедро
         ax.plot([], [], '-o', color='green')[0],  # Голень
         ax.plot([], [], '-o', color='green')[0],  # Каромысло голени
         ax.plot([], [], '-o', color='purple')[0],  # Длинная тяга голени
         ax.plot([], [], '-o', color='brown')[0],  # Рычаг двигателя 3
         ax.plot([], [], 'go')[0],  # Ступня
         ax.plot([], [], 'ro')[0]]  # Целевая точка (ступня)

# Создание анимации
ani = animation.FuncAnimation(fig, update, frames=100, interval=50, blit=True)

plt.show()
