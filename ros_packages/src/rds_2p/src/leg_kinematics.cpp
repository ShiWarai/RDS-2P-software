#include "leg_kinematics.hpp"
#include <algorithm>
#include <limits>

namespace rds_2p {

std::vector<Point> LegKinematics::circleIntersection(double x1, double y1, double r1,
                                                     double x2, double y2, double r2) {
    std::vector<Point> result;
    
    double d = hypot2(x2 - x1, y2 - y1);
    
    // Проверяем условия пересечения
    if (d > r1 + r2 + EPSILON || d < std::abs(r1 - r2) - EPSILON || 
        (std::abs(d) < EPSILON && std::abs(r1 - r2) < EPSILON)) {
        return result; // Нет пересечений
    }
    
    double a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
    double h_sq = std::max(0.0, r1 * r1 - a * a);
    double h = std::sqrt(h_sq);
    
    double xm = x1 + a * (x2 - x1) / d;
    double ym = y1 + a * (y2 - y1) / d;
    
    if (h < EPSILON) {
        // Одна точка (касание)
        result.emplace_back(xm, ym);
    } else {
        // Две точки
        double x3 = xm + h * (y2 - y1) / d;
        double y3 = ym - h * (x2 - x1) / d;
        double x4 = xm - h * (y2 - y1) / d;
        double y4 = ym + h * (x2 - x1) / d;
        
        result.emplace_back(x3, y3);
        result.emplace_back(x4, y4);
    }
    
    return result;
}

std::optional<std::pair<double, double>> LegKinematics::computeMotorAngles(double target_x, double target_y) {
    // Находим положение колена (K)
    auto intersections = circleIntersection(0, 0, L_HIP, target_x, target_y, L_LEG);
    if (intersections.empty()) {
        return std::nullopt;
    }
    
    // Выбираем точку с меньшим X
    auto knee_it = std::min_element(intersections.begin(), intersections.end(),
                                   [](const Point& a, const Point& b) { return a.x < b.x; });
    Point knee = *knee_it;
    
    // Угол бедра (motor2)
    double theta_hip = std::atan2(knee.y, knee.x);
    
    // Угол голени
    double d = hypot2(target_x, target_y);
    double cos_angle_leg = (d * d - L_HIP * L_HIP - L_LEG * L_LEG) / (2.0 * L_HIP * L_LEG);
    if (std::abs(cos_angle_leg) > 1.0) {
        return std::nullopt;
    }
    double theta_leg = std::acos(cos_angle_leg); // Угол всегда положительный
    
    // Конец каромысла (B_ext)
    double B_ext_x = knee.x + L_CAROMYSLO * std::cos(theta_hip + theta_leg + L_CAROMYSLO_ANGLE);
    double B_ext_y = knee.y + L_CAROMYSLO * std::sin(theta_hip + theta_leg + L_CAROMYSLO_ANGLE);
    
    // Точка D (конец стороны A качалки)
    intersections = circleIntersection(0, 0, L_SIDE_A, B_ext_x, B_ext_y, L_TYAGA);
    if (intersections.empty()) {
        return std::nullopt;
    }
    auto D_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.y < b.y; });
    Point D = *D_it;
    
    // Точка P (конец стороны B качалки)
    double alpha = std::atan2(D.y, D.x);
    double beta = alpha - L_SIDE_C_ANGLE_DEG * DEG_TO_RAD;
    double P_x = L_SIDE_B * std::cos(beta);
    double P_y = L_SIDE_B * std::sin(beta);
    
    // Точка R (конец рычага двигателя 3)
    intersections = circleIntersection(OFFSET_3_X, OFFSET_3_Y, L_RICHAG_3, P_x, P_y, L_MALA_TYAGA);
    if (intersections.empty()) {
        return std::nullopt;
    }
    auto R_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.x < b.x; });
    Point R = *R_it;
    
    // Угол двигателя 3
    double theta_dvigatel_3 = std::atan2(R.y - OFFSET_3_Y, R.x - OFFSET_3_X);
    
    double motor2_angle = (theta_hip + 2.0 * M_PI) * RAD_TO_DEG;
    double motor3_angle = theta_dvigatel_3 * RAD_TO_DEG;
    
    return std::pair<double, double>{motor2_angle, motor3_angle};
}

InverseKinematicsResult LegKinematics::inverseKinematics(double target_x, double target_y) {
    InverseKinematicsResult result;
    
    auto motor_angles = computeMotorAngles(target_x, target_y);
    if (!motor_angles.has_value()) {
        result.error_message = "Ошибка: Невозможно вычислить углы (нет пересечений или некорректная конфигурация).";
        return result;
    }
    
    result.motor2_angle_deg = motor_angles->first;
    result.motor3_angle_deg = motor_angles->second;
    
    // Вычисляем позиции для визуализации
    auto intersections = circleIntersection(0, 0, L_HIP, target_x, target_y, L_LEG);
    auto knee_it = std::min_element(intersections.begin(), intersections.end(),
                                   [](const Point& a, const Point& b) { return a.x < b.x; });
    Point knee = *knee_it;
    
    double theta_hip = std::atan2(knee.y, knee.x);
    double d = hypot2(target_x, target_y);
    double cos_angle_leg = (d * d - L_HIP * L_HIP - L_LEG * L_LEG) / (2.0 * L_HIP * L_LEG);
    double theta_leg = std::acos(cos_angle_leg);
    
    double B_ext_x = knee.x + L_CAROMYSLO * std::cos(theta_hip + theta_leg + L_CAROMYSLO_ANGLE);
    double B_ext_y = knee.y + L_CAROMYSLO * std::sin(theta_hip + theta_leg + L_CAROMYSLO_ANGLE);
    
    intersections = circleIntersection(0, 0, L_SIDE_A, B_ext_x, B_ext_y, L_TYAGA);
    auto D_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.y < b.y; });
    Point D = *D_it;
    
    double alpha = std::atan2(D.y, D.x);
    double beta = alpha - L_SIDE_C_ANGLE_DEG * DEG_TO_RAD;
    double P_x = L_SIDE_B * std::cos(beta);
    double P_y = L_SIDE_B * std::sin(beta);
    
    intersections = circleIntersection(OFFSET_3_X, OFFSET_3_Y, L_RICHAG_3, P_x, P_y, L_MALA_TYAGA);
    auto R_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.x < b.x; });
    Point R = *R_it;
    
    // Заполняем позиции
    result.origin = Point(0, 0);
    result.knee = knee;
    result.B_ext = Point(B_ext_x, B_ext_y);
    result.D = D;
    result.P = Point(P_x, P_y);
    result.R = R;
    result.foot = Point(target_x, target_y);
    
    return result;
}

std::optional<double> LegKinematics::computeAngleBetweenHipAndShin(double theta2_deg, double theta3_deg) {
    double theta2 = (theta2_deg + 180.0) * DEG_TO_RAD;
    double theta3 = theta3_deg * DEG_TO_RAD;
    
    double K_x = L_HIP * std::cos(theta2);
    double K_y = L_HIP * std::sin(theta2);
    double R_x = OFFSET_3_X + L_RICHAG_3 * std::cos(theta3);
    double R_y = OFFSET_3_Y + L_RICHAG_3 * std::sin(theta3);
    
    auto intersections = circleIntersection(0, 0, L_SIDE_B, R_x, R_y, L_MALA_TYAGA);
    if (intersections.empty()) {
        return std::nullopt;
    }
    auto P_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.y < b.y; });
    Point P = *P_it;
    
    double alpha = std::atan2(P.y, P.x) + L_SIDE_C_ANGLE_DEG * DEG_TO_RAD;
    double D_x = L_SIDE_A * std::cos(alpha);
    double D_y = L_SIDE_A * std::sin(alpha);
    
    intersections = circleIntersection(D_x, D_y, L_TYAGA, K_x, K_y, L_CAROMYSLO);
    if (intersections.empty()) {
        return std::nullopt;
    }
    auto B_ext_it = std::max_element(intersections.begin(), intersections.end(),
                                    [](const Point& a, const Point& b) { return a.y < b.y; });
    Point B_ext = *B_ext_it;
    
    double psi = std::atan2(B_ext.y - K_y, B_ext.x - K_x);
    double theta_leg = normalizeAngle(psi - theta2 - L_CAROMYSLO_ANGLE);
    
    return 180.0 - theta_leg * RAD_TO_DEG;
}

DirectKinematicsResult LegKinematics::directKinematics(double theta2_deg, double theta3_deg) {
    DirectKinematicsResult result;
    result.motor2_angle_deg = theta2_deg;
    result.motor3_angle_deg = theta3_deg;
    
    double theta2 = (theta2_deg + 180.0) * DEG_TO_RAD;
    double theta3 = theta3_deg * DEG_TO_RAD;
    
    double K_x = L_HIP * std::cos(theta2);
    double K_y = L_HIP * std::sin(theta2);
    double R_x = OFFSET_3_X + L_RICHAG_3 * std::cos(theta3);
    double R_y = OFFSET_3_Y + L_RICHAG_3 * std::sin(theta3);
    
    // Точка P
    auto intersections = circleIntersection(0, 0, L_SIDE_B, R_x, R_y, L_MALA_TYAGA);
    if (intersections.empty()) {
        result.error_message = "Ошибка: Нет пересечений для точки P.";
        return result;
    }
    
    Point P;
    if (intersections.size() == 1) {
        P = intersections[0];
        result.warnings.push_back("Предупреждение: Одно пересечение для точки P.");
    } else {
        auto P_it = std::max_element(intersections.begin(), intersections.end(),
                                    [](const Point& a, const Point& b) { return a.y < b.y; });
        P = *P_it;
    }
    
    double alpha = std::atan2(P.y, P.x) + L_SIDE_C_ANGLE_DEG * DEG_TO_RAD;
    double D_x = L_SIDE_A * std::cos(alpha);
    double D_y = L_SIDE_A * std::sin(alpha);
    
    // Точка B_ext
    intersections = circleIntersection(D_x, D_y, L_TYAGA, K_x, K_y, L_CAROMYSLO);
    if (intersections.empty()) {
        result.error_message = "Ошибка: Нет пересечений для точки B_ext.";
        return result;
    }
    
    Point B_ext;
    if (intersections.size() == 1) {
        B_ext = intersections[0];
        result.warnings.push_back("Предупреждение: Одно пересечение для точки B_ext.");
    } else {
        // Выбираем точку с минимальным отклонением от ожидаемого угла
        auto B_ext_it = std::min_element(intersections.begin(), intersections.end(),
                                        [&](const Point& a, const Point& b) {
                                            double angle_a = std::atan2(a.y - K_y, a.x - K_x) - theta2 - L_CAROMYSLO_ANGLE;
                                            double angle_b = std::atan2(b.y - K_y, b.x - K_x) - theta2 - L_CAROMYSLO_ANGLE;
                                            angle_a = normalizeAngle(angle_a);
                                            angle_b = normalizeAngle(angle_b);
                                            double knee_angle_a = 180.0 - angle_a * RAD_TO_DEG;
                                            double knee_angle_b = 180.0 - angle_b * RAD_TO_DEG;
                                            return std::abs(knee_angle_a) < std::abs(knee_angle_b);
                                        });
        B_ext = *B_ext_it;
    }
    
    double theta_leg = normalizeAngle(std::atan2(B_ext.y - K_y, B_ext.x - K_x) - theta2 - L_CAROMYSLO_ANGLE);
    double knee_angle_deg = (180.0 - theta_leg * RAD_TO_DEG);
    
    // Нормализуем угол в диапазон [0, 360]
    while (knee_angle_deg < 0) knee_angle_deg += 360.0;
    while (knee_angle_deg >= 360) knee_angle_deg -= 360.0;
    
    if (knee_angle_deg < 0) {
        result.warnings.push_back("Предупреждение: Угол между бедром и голенью отрицательный (" + 
                                 std::to_string(knee_angle_deg) + "°).");
    }
    
    result.angle_between_hip_and_shin_deg = knee_angle_deg;
    
    // Вычисляем позицию ступни
    double F_x = K_x + L_LEG * std::cos(theta2 + theta_leg);
    double F_y = K_y + L_LEG * std::sin(theta2 + theta_leg);
    
    // Заполняем позиции
    result.origin = Point(0, 0);
    result.knee = Point(K_x, K_y);
    result.B_ext = B_ext;
    result.D = Point(D_x, D_y);
    result.P = P;
    result.R = Point(R_x, R_y);
    result.foot = Point(F_x, F_y);
    
    return result;
}

double LegKinematics::normalizeAngle(double angle) {
    while (angle < 0) angle += 2.0 * M_PI;
    while (angle >= 2.0 * M_PI) angle -= 2.0 * M_PI;
    return angle;
}

double LegKinematics::hypot2(double dx, double dy) {
    return std::sqrt(dx * dx + dy * dy);
}

std::optional<double> LegKinematics::inverseKinematicsForShinMotor(double motor_2_angle_rad, double hip_shin_angle_rad) {
    // ========== ВХОДНЫЕ ПАРАМЕТРЫ ==========
    // motor_2_angle_rad - угол мотора 2 (бедра) в радианах (ИНВЕРТИРОВАННЫЙ)
    // hip_shin_angle_rad - угол между бедром и голенью в радианах
    
    // ========== ВЫЧИСЛЕНИЕ ПОЗИЦИИ КОЛЕНА ==========
    // Преобразуем угол мотора бедра в радианы и добавляем смещение 180°
    // theta_hip - угол бедра в радианах (от горизонтали до линии бедро-колено)
    // ИНВЕРТИРУЕМ угол мотора: -motor_2_angle_rad вместо +motor_2_angle_rad
    double theta_hip = (-motor_2_angle_rad + 180.0 * DEG_TO_RAD);
    
    // knee_x, knee_y - координаты колена, вычисленные по углу мотора бедра
    // Колено находится на конце бедра длиной L_HIP под углом theta_hip
    double knee_x = L_HIP * std::cos(theta_hip);
    double knee_y = L_HIP * std::sin(theta_hip);
    
    // ========== ВЫЧИСЛЕНИЕ УГЛА ГОЛЕНИ ==========
    // theta_leg - угол между бедром и голенью в радианах
    // Преобразуем входной угол из радиан в радианы (убираем DEG_TO_RAD)
    double theta_leg = (M_PI - hip_shin_angle_rad);
    
    // ========== ВЫЧИСЛЕНИЕ ПОЗИЦИИ КАРОМЫСЛА ==========
    // B_ext_x, B_ext_y - координаты конца каромысла голени
    // Каромысло отходит от колена под углом (theta_hip + theta_leg + L_CAROMYSLO_ANGLE)
    // L_CAROMYSLO_ANGLE - фиксированный угол каромысла (π - 32.2°)
    double B_ext_x = knee_x + L_CAROMYSLO * std::cos(theta_hip + theta_leg + L_CAROMYSLO_ANGLE);
    double B_ext_y = knee_y + L_CAROMYSLO * std::sin(theta_hip + theta_leg + L_CAROMYSLO_ANGLE);
    
    // ========== ПОИСК ТОЧКИ D (КАЧАЛКА) ==========
    // intersections - точки пересечения окружностей для поиска точки D:
    //   - окружность 1: центр (0,0), радиус L_SIDE_A (длина стороны A качалки = 2.4 см)
    //   - окружность 2: центр (B_ext_x, B_ext_y), радиус L_TYAGA (длина тяги = 10.0 см)
    auto intersections = circleIntersection(0, 0, L_SIDE_A, B_ext_x, B_ext_y, L_TYAGA);
    if (intersections.empty()) {
        return std::nullopt; // Нет пересечений - механизм не может быть собран
    }
    
    // D_it - итератор к точке D с максимальной Y-координатой (верхняя точка)
    auto D_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.y < b.y; });
    // D - структура Point с координатами точки D (D.x, D.y)
    Point D = *D_it;
    
    // ========== ВЫЧИСЛЕНИЕ ТОЧКИ P (КАЧАЛКА) ==========
    // alpha - угол от начала координат до точки D
    double alpha = std::atan2(D.y, D.x);
    
    // beta - угол для точки P (повернут на L_SIDE_C_ANGLE_DEG относительно alpha)
    // L_SIDE_C_ANGLE_DEG = 90° - фиксированный угол между сторонами A и C качалки
    double beta = alpha - L_SIDE_C_ANGLE_DEG * DEG_TO_RAD;
    
    // P_x, P_y - координаты точки P (конец стороны B качалки)
    // L_SIDE_B = 2.7 см - длина стороны B качалки
    double P_x = L_SIDE_B * std::cos(beta);
    double P_y = L_SIDE_B * std::sin(beta);
    
    // ========== ПОИСК ТОЧКИ R (РЫЧАГ ДВИГАТЕЛЯ 3) ==========
    // intersections - точки пересечения окружностей для поиска точки R:
    //   - окружность 1: центр (OFFSET_3_X, OFFSET_3_Y), радиус L_RICHAG_3 (рычаг двигателя 3 = 2.4 см)
    //   - окружность 2: центр (P_x, P_y), радиус L_MALA_TYAGA (малая тяга = 2.8 см)
    // OFFSET_3_X = 2.0 см, OFFSET_3_Y = -2.0 см - смещение оси двигателя 3
    intersections = circleIntersection(OFFSET_3_X, OFFSET_3_Y, L_RICHAG_3, P_x, P_y, L_MALA_TYAGA);
    if (intersections.empty()) {
        return std::nullopt; // Нет пересечений - механизм не может быть собран
    }
    
    // R_it - итератор к точке R с максимальной X-координатой (правая точка)
    auto R_it = std::max_element(intersections.begin(), intersections.end(),
                                [](const Point& a, const Point& b) { return a.x < b.x; });
    // R - структура Point с координатами точки R (R.x, R.y)
    Point R = *R_it;
    
    // ========== ВЫЧИСЛЕНИЕ УГЛОВ ДВИГАТЕЛЕЙ ==========
    // theta_dvigatel_3 - угол рычага двигателя 3 в радианах
    // (угол от горизонтали до линии центр_двигателя3-R)
    double theta_dvigatel_3 = std::atan2(R.y - OFFSET_3_Y, R.x - OFFSET_3_X);
    
    // motor2_angle - угол двигателя 2 в радианах (бедро)
    // Добавляем 2π для нормализации угла в положительный диапазон
    double motor2_angle = (theta_hip + 2.0 * M_PI);
    
    // motor3_angle - угол двигателя 3 в радианах (голень) - ЭТО НАШ РЕЗУЛЬТАТ
    double motor3_angle = theta_dvigatel_3;
    
    return motor3_angle; // Возвращаем угол мотора голени в радианах
}

} // namespace rds_2p
