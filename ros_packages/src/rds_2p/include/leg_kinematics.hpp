#pragma once

#include <vector>
#include <optional>
#include <string>
#include <cmath>

namespace rds_2p {

// Структура для представления точки
struct Point {
    double x;
    double y;
    
    Point(double x = 0.0, double y = 0.0) : x(x), y(y) {}
};

// Структура для результата обратной кинематики
struct InverseKinematicsResult {
    std::optional<double> motor2_angle_deg;  // Угол двигателя 2 в градусах
    std::optional<double> motor3_angle_deg;  // Угол двигателя 3 в градусах
    std::string error_message;              // Сообщение об ошибке, если есть
    
    // Позиции точек для визуализации
    Point origin;
    Point knee;
    Point B_ext;
    Point D;
    Point P;
    Point R;
    Point foot;
    
    InverseKinematicsResult() : motor2_angle_deg(std::nullopt), motor3_angle_deg(std::nullopt) {}
};

// Структура для результата прямой кинематики
struct DirectKinematicsResult {
    std::optional<double> angle_between_hip_and_shin_deg;  // Угол между бедром и голенью в градусах
    double motor2_angle_deg;
    double motor3_angle_deg;
    std::string error_message;
    std::vector<std::string> warnings;
    
    // Позиции точек для визуализации
    Point origin;
    Point knee;
    Point B_ext;
    Point D;
    Point P;
    Point R;
    Point foot;
    
    DirectKinematicsResult() : angle_between_hip_and_shin_deg(std::nullopt), motor2_angle_deg(0.0), motor3_angle_deg(0.0) {}
};

class LegKinematics {
public:
    // Константы кинематики ноги
    static constexpr double L_LEG = 10.255;        // длина голени
    static constexpr double L_HIP = 10.0;          // длина бедра
    static constexpr double L_CAROMYSLO = 3.191;   // длина каромысла голени
    static constexpr double L_CAROMYSLO_ANGLE = M_PI - (32.2 * M_PI / 180.0);  // угол каромысла в радианах
    static constexpr double L_TYAGA = 10.0;        // длина длинной тяги голени
    static constexpr double L_SIDE_A = 2.4;        // длина стороны A качалки
    static constexpr double L_SIDE_B = 2.7;        // длина стороны B качалки
    static constexpr double L_SIDE_C_ANGLE_DEG = 90.0;  // угол в градусах
    static constexpr double L_MALA_TYAGA = 2.8;    // длина малой тяги
    static constexpr double L_RICHAG_3 = 2.4;      // длина рычага двигателя 3
    
    // Смещение оси двигателя 3
    static constexpr double OFFSET_3_X = 2.0;
    static constexpr double OFFSET_3_Y = -2.0;
    
    // Константы для вычислений
    static constexpr double EPSILON = 1e-6;
    static constexpr double DEG_TO_RAD = M_PI / 180.0;
    static constexpr double RAD_TO_DEG = 180.0 / M_PI;

public:
    /**
     * Вычисляет точки пересечения двух окружностей.
     * @param x1, y1, r1 - центр и радиус первой окружности
     * @param x2, y2, r2 - центр и радиус второй окружности
     * @return вектор точек пересечения или пустой вектор, если пересечений нет
     */
    static std::vector<Point> circleIntersection(double x1, double y1, double r1,
                                                double x2, double y2, double r2);
    
    /**
     * Вычисляет углы двигателей на основе целевых координат ступни (обратная кинематика).
     * @param target_x - координата X ступни
     * @param target_y - координата Y ступни
     * @return результат с углами двигателей или ошибкой
     */
    static InverseKinematicsResult inverseKinematics(double target_x, double target_y);
    
    /**
     * Вычисляет угол между бедром и голенью по углам двигателей.
     * @param theta2_deg - угол двигателя 2 в градусах
     * @param theta3_deg - угол двигателя 3 в градусах
     * @return угол в градусах или std::nullopt, если решение невозможно
     */
    static std::optional<double> computeAngleBetweenHipAndShin(double theta2_deg, double theta3_deg);
    
    /**
     * Выполняет прямую кинематику.
     * @param theta2_deg - угол двигателя 2 в градусах
     * @param theta3_deg - угол двигателя 3 в градусах
     * @return результат с углом между бедром и голенью и позициями точек
     */
    static DirectKinematicsResult directKinematics(double theta2_deg, double theta3_deg);
    
    /**
     * Вычисляет угол мотора голени по углу мотора бедра и углу между бедром и голенью.
     * @param motor_2_angle_rad - угол мотора бедра в радианах (инвертированный)
     * @param hip_shin_angle_rad - угол между бедром и голенью в радианах
     * @return угол мотора голени в радианах или std::nullopt, если решение невозможно
     */
    static std::optional<double> inverseKinematicsForShinMotor(double motor_2_angle_rad, double hip_shin_angle_rad);

private:
    /**
     * Вспомогательная функция для вычисления углов двигателей.
     * @param target_x - координата X ступни
     * @param target_y - координата Y ступни
     * @return пара (motor2_angle, motor3_angle) в градусах или std::nullopt
     */
    static std::optional<std::pair<double, double>> computeMotorAngles(double target_x, double target_y);
    
    /**
     * Нормализует угол в диапазон [0, 2π].
     * @param angle - угол в радианах
     * @return нормализованный угол
     */
    static double normalizeAngle(double angle);
    
    /**
     * Вычисляет расстояние между двумя точками.
     * @param dx - разность по X
     * @param dy - разность по Y
     * @return расстояние
     */
    static double hypot2(double dx, double dy);
};

} // namespace rds_2p
