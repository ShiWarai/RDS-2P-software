# Привязка одного мотора к joint
uint8 motor_id              # ID мотора
string joint_name           # Имя joint
string motor_name           # Имя мотора в конфигурации
string motor_type           # Тип мотора (SCS40, etc.)
bool reversed               # Инвертировано ли направление вращения
float64 zero_offset         # Смещение нуля в радианах
float64 min_position        # Минимальная позиция в радианах
float64 max_position        # Максимальная позиция в радианах
float64 max_velocity        # Максимальная скорость в рад/с
float64 max_acceleration    # Максимальное ускорение в рад/с²
