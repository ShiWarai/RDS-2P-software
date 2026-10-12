import numpy as np
from leg import direct_kinematics

def main():
    """
    Скрипт для ввода углов двигателей через консоль и получения угла между бедром и голенью.
    """
    print("Введите углы двигателей (в градусах):")
    
    try:
        # Ввод углов
        theta2_deg = float(input("Угол двигателя 2 (бедро): "))
        theta3_deg = float(input("Угол двигателя 3 (голень): "))
        
        # Вызов функции direct_kinematics
        result = direct_kinematics(theta2_deg, theta3_deg)
        
        # Проверка результата
        if isinstance(result, str):
            print(result)
        else:
            angle_hip_shin = result["angle_between_hip_and_shin"]
            print(f"\nУгол между бедром и голенью: {angle_hip_shin:.2f} градусов")
    
    except ValueError:
        print("Ошибка: Пожалуйста, введите числовые значения для углов.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    main()