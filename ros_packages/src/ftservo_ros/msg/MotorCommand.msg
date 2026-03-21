# Команда управления для одного мотора (без enable/disable)
uint8 motor_id

# Целевые значения (опциональные)
float64 target_position     # Целевая позиция в радианах
float64 target_velocity     # Целевая скорость в рад/с
float64 target_acceleration # Целевое ускорение в рад/с²