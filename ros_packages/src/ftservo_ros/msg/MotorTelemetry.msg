# Телеметрические данные одного мотора (только некритичные данные)
uint8 motor_id

# Некритичные данные
string joint_name           # Имя привязанного joint
float64 effort              # Текущее усилие (ток в А)
float64 temperature         # Температура мотора в °C
float64 voltage             # Напряжение питания в В
float64 current             # Ток потребления в А
uint8 error_code            # Код ошибки
