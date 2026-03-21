/**
 * @file servo_calibration.cpp
 * @brief Программа калибровки сервоприводов ноги робота
 * @description Калибрует начальные позиции и пределы движения сервоприводов в "умном" режиме
 */

#include "SCSCL.hpp"
#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <map>
#include <cmath>
#include <thread>
#include <chrono>
#include <termios.h>
#include <unistd.h>
#include <sys/select.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// Константы
const std::string DEVICENAME = "/dev/ttyS7";
const int BAUDRATE = 500000;
const std::vector<int> TARGET_LOADS = {150, 150, 150};  // Целевая нагрузка для каждого сервопривода
const int MOVE_SPEED = 100;
const int MOVE_ACC = 1;
const std::string DEFAULT_CALIBRATION_FILE = "legs_calibration.json";

// Структура для хранения калибровочных данных
struct ServoCalibrationData {
    int initial_position;
    int min_position;
    int max_position;
    
    json to_json() const {
        return {
            {"initial_position", initial_position},
            {"min_position", min_position},
            {"max_position", max_position}
        };
    }
    
    static ServoCalibrationData from_json(const json& j) {
        return {
            j["initial_position"].get<int>(),
            j["min_position"].get<int>(),
            j["max_position"].get<int>()
        };
    }
};

// Функция ожидания нажатия Enter
void wait_for_enter() {
    std::cout << "Нажмите Enter, чтобы продолжить..." << std::endl;
    
    // Очищаем буфер, если в нем что-то есть
    if (std::cin.rdbuf()->in_avail() > 0) {
        std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
    }
    
    // Ждём нажатия Enter
    std::string dummy;
    std::getline(std::cin, dummy);
}

// Функция проверки доступности ввода
bool input_available() {
    struct timeval tv;
    fd_set fds;
    tv.tv_sec = 0;
    tv.tv_usec = 0;
    FD_ZERO(&fds);
    FD_SET(STDIN_FILENO, &fds);
    select(STDIN_FILENO + 1, &fds, nullptr, nullptr, &tv);
    return (FD_ISSET(0, &fds));
}

// Функция поиска пределов по нагрузке
std::pair<int, int> find_limits_by_load(
    SCSCL& servo_controller,
    uint8_t servo_id,
    int base_pos,
    int target_load
) {
    std::cout << "\nПоиск пределов для сервопривода " << static_cast<int>(servo_id) << std::endl;
    std::cout << "Целевая нагрузка: " << target_load << std::endl;
    std::cout << "Нажмите Ctrl+C, чтобы остановить" << std::endl;
    
    int min_pos = base_pos;
    int max_pos = base_pos;
    
    try {
        // Сначала найдем максимальную позицию
        std::cout << "\nПоиск максимальной позиции..." << std::endl;
        int current_pos = base_pos;
        
        while (true) {
            current_pos += 1;
            int current_load = servo_controller.ReadLoad(servo_id);
            
            std::cout << "Текущая позиция: " << current_pos 
                      << ", Нагрузка: " << current_load << std::endl;
            
            if (std::abs(current_load) >= target_load) {
                std::cout << "\nМаксимальная позиция найдена!" << std::endl;
                std::cout << "Позиция: " << current_pos << std::endl;
                std::cout << "Нагрузка: " << current_load << std::endl;
                max_pos = current_pos;
                break;
            }
            
            servo_controller.WritePos(servo_id, current_pos, 0, MOVE_SPEED, MOVE_ACC);
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        
        // Возвращение в начальную позицию
        std::cout << "\nВозвращение в начальную позицию..." << std::endl;
        servo_controller.WritePos(servo_id, base_pos, 1000, 0, 0);
        std::this_thread::sleep_for(std::chrono::milliseconds(3000));
        
        // Теперь найдем минимальную позицию
        std::cout << "\nПоиск минимальной позиции..." << std::endl;
        current_pos = servo_controller.ReadPos(servo_id);
        
        while (true) {
            current_pos -= 1;
            int current_load = servo_controller.ReadLoad(servo_id);
            
            std::cout << "Текущая позиция: " << current_pos 
                      << ", Нагрузка: " << current_load << std::endl;
            
            if (std::abs(current_load) >= target_load) {
                std::cout << "\nМинимальная позиция найдена!" << std::endl;
                std::cout << "Позиция: " << current_pos << std::endl;
                std::cout << "Нагрузка: " << current_load << std::endl;
                min_pos = current_pos;
                break;
            }
            
            servo_controller.WritePos(servo_id, current_pos, 0, MOVE_SPEED, MOVE_ACC);
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }

        // Возвращение в начальную позицию
        std::cout << "\nВозвращение в начальную позицию..." << std::endl;
        servo_controller.WritePos(servo_id, base_pos, 1000, 0, 0);
        std::this_thread::sleep_for(std::chrono::milliseconds(3000));
        
        std::cout << "\nКалибровка для сервопривода " << static_cast<int>(servo_id) 
                  << " завершена!" << std::endl;
        std::cout << "Минимальная позиция: " << min_pos << std::endl;
        std::cout << "Максимальная позиция: " << max_pos << std::endl;
        std::cout << "Общий диапазон: " << (max_pos - min_pos) << std::endl;
        
    } catch (const std::exception& e) {
        std::cerr << "Ошибка: " << e.what() << std::endl;
    }
    
    return {min_pos, max_pos};
}

// Функция валидации позиции первого сервопривода
int validate_first_servo_position(SCSCL& servo_controller, uint8_t servo_id) {
    while (true) {
        std::cout << "\nЭтап 1: Установите сервопривод " << static_cast<int>(servo_id) 
                  << " примерно на 90 градусов" << std::endl;
        wait_for_enter();
        
        int position = servo_controller.ReadPos(servo_id);
        
        if (position < 0) {
            std::cout << "Некорректное значение позиции: " << position << std::endl;
            std::cout << "Пожалуйста, установите сервопривод " << static_cast<int>(servo_id) 
                      << " снова примерно на 90 градусов" << std::endl;
            continue;
        }
        
        std::cout << "Начальная позиция записана: " << position << std::endl;
        return position;
    }
}

// Функция калибровки начальных позиций
std::map<uint8_t, ServoCalibrationData> calibrate_initial_positions(
    SCSCL& servo_controller,
    const std::vector<uint8_t>& servo_ids
) {
    std::map<uint8_t, ServoCalibrationData> calibration_data;
    
    for (size_t i = 0; i < servo_ids.size(); ++i) {
        uint8_t servo_id = servo_ids[i];
        std::cout << "\nКалибровка сервопривода " << static_cast<int>(servo_id) << std::endl;
        servo_controller.EnableTorque(servo_id, 0);
        
        int initial_position = -1;
        
        // Этап 1: Начальная позиция
        if (i == 0) {
            initial_position = validate_first_servo_position(servo_controller, servo_id);
        } else {
            while (true) {
                std::cout << "Этап 1: Зафиксируйте сервопривод " 
                          << static_cast<int>(servo_id) << std::endl;
                wait_for_enter();
                
                int position = servo_controller.ReadPos(servo_id);
                if (position < 0) {
                    std::cout << "Некорректное значение позиции: " << position << std::endl;
                    std::cout << "Пожалуйста, установите сервопривод " 
                              << static_cast<int>(servo_id) << " снова" << std::endl;
                    continue;
                }
                
                initial_position = position;
                std::cout << "Начальная позиция записана: " << initial_position << std::endl;
                break;
            }
        }
        
        calibration_data[servo_id] = {
            initial_position,
            initial_position,
            initial_position
        };
    }
    
    return calibration_data;
}

// Функция перемещения в крайнее положение
void move_to_extreme_position(
    SCSCL& servo_controller,
    uint8_t servo_id,
    int initial_pos,
    int min_pos,
    int max_pos
) {
    int distance_to_min = std::abs(initial_pos - min_pos);
    int distance_to_max = std::abs(initial_pos - max_pos);
    
    int target_pos = (distance_to_max > distance_to_min) ? max_pos : min_pos;
    std::cout << "\nПеремещение сервопривода " << static_cast<int>(servo_id) 
              << " в крайнюю позицию: " << target_pos << std::endl;
    servo_controller.WritePos(servo_id, target_pos, 1000, 0, 0);
    std::this_thread::sleep_for(std::chrono::milliseconds(3000));
}

// "Умная" калибровка пределов
std::map<uint8_t, ServoCalibrationData> smart_calibration(
    SCSCL& servo_controller,
    const std::vector<uint8_t>& servo_ids,
    std::map<uint8_t, ServoCalibrationData>& calibration_data
) {
    std::cout << "\n=== Умная калибровка пределов ===" << std::endl;
    wait_for_enter();
    
    // Сохраняем начальную позицию первого серво
    uint8_t first_servo_id = servo_ids[0];
    int first_servo_initial_pos = calibration_data[first_servo_id].initial_position;
    std::cout << "\nУдерживаем сервопривод " << static_cast<int>(first_servo_id) 
              << " в его начальной позиции: " << first_servo_initial_pos << std::endl;
    
    // Этап 2: поиск пределов в определенном порядке (второй -> третий -> первый)
    std::vector<uint8_t> calibration_order = {servo_ids[1], servo_ids[2], servo_ids[0]};
    
    for (uint8_t servo_id : calibration_order) {
        ServoCalibrationData& data = calibration_data[servo_id];
        
        // Для второго и третьего серво, убедимся что первый серво остается в записанной начальной позиции
        if (servo_id == servo_ids[1] || servo_id == servo_ids[2]) {
            std::cout << "\nКалибровка сервопривода " << static_cast<int>(servo_id) 
                      << " с удержанием сервопривода " << static_cast<int>(first_servo_id) 
                      << " в позиции " << first_servo_initial_pos << std::endl;
            servo_controller.WritePos(first_servo_id, first_servo_initial_pos, 0, 0, 0);
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            
            // При калибровке второго серво, убедимся что третий может свободно двигаться
            if (servo_id == servo_ids[1]) {
                std::cout << "Сервопривод " << static_cast<int>(servo_ids[2]) 
                          << " может свободно двигаться во время калибровки" << std::endl;
                servo_controller.EnableTorque(servo_ids[2], 0);
            }
            // При калибровке третьего серво, убедимся что второй может свободно двигаться
            else if (servo_id == servo_ids[2]) {
                std::cout << "Сервопривод " << static_cast<int>(servo_ids[1]) 
                          << " может свободно двигаться во время калибровки" << std::endl;
                servo_controller.EnableTorque(servo_ids[1], 0);
            }
        }
        
        // Получаем целевую нагрузку на основе положения серво в ноге (1-й, 2-й или 3-й)
        size_t servo_index = std::distance(
            servo_ids.begin(), 
            std::find(servo_ids.begin(), servo_ids.end(), servo_id)
        );
        int target_load = TARGET_LOADS[servo_index];
        
        auto [min_pos, max_pos] = find_limits_by_load(
            servo_controller, 
            servo_id, 
            data.initial_position,
            target_load
        );
        data.min_position = min_pos;
        data.max_position = max_pos;

        // Убедимся, что третий сервопривод может свободно двигаться во время калибровки первого
        if (servo_id == servo_ids[2]) {
            std::cout << "Сервопривод " << static_cast<int>(servo_ids[2]) 
                      << " может свободно двигаться во время калибровки сервопривода " 
                      << static_cast<int>(first_servo_id) << std::endl;
            servo_controller.EnableTorque(servo_ids[2], 0);
            
            // После калибровки третьего серво, перемещаем второй в крайнее положение
            std::cout << "\nПеремещаем сервопривод " << static_cast<int>(servo_ids[1]) 
                      << " в крайнее положение перед калибровкой сервопривода " 
                      << static_cast<int>(first_servo_id) << std::endl;
            move_to_extreme_position(
                servo_controller,
                servo_ids[1],
                calibration_data[servo_ids[1]].initial_position,
                calibration_data[servo_ids[1]].min_position,
                calibration_data[servo_ids[1]].max_position
            );
        }
    }
    
    return calibration_data;
}

// Сохранение калибровочных данных
void save_calibration_data(
    const std::map<uint8_t, ServoCalibrationData>& calibration_data,
    const std::vector<uint8_t>& servo_ids,
    const std::string& calibration_file
) {
    json existing_data;
    
    // Загружаем существующие данные, если файл существует
    std::ifstream input_file(calibration_file);
    if (input_file.is_open()) {
        try {
            input_file >> existing_data;
        } catch (const json::exception& e) {
            std::cerr << "Внимание: Не удалось прочитать " << calibration_file 
                      << ", создается новый файл" << std::endl;
            existing_data = json::object();
        }
        input_file.close();
    }
    
    // Обновляем данные для откалиброванных серво
    for (uint8_t servo_id : servo_ids) {
        std::string key = std::to_string(servo_id);
        existing_data[key] = calibration_data.at(servo_id).to_json();
    }
    
    // Сохраняем обновленные данные
    std::ofstream output_file(calibration_file);
    if (output_file.is_open()) {
        output_file << existing_data.dump(4);
        output_file.close();
        std::cout << "\n✅ Данные калибровки сохранены в " << calibration_file << std::endl;
    } else {
        std::cerr << "Ошибка: Не удалось открыть файл " << calibration_file 
                  << " для записи" << std::endl;
    }
}

// Загрузка калибровочных данных
std::map<uint8_t, ServoCalibrationData> load_calibration_data(
    const std::vector<uint8_t>& servo_ids,
    const std::string& calibration_file
) {
    std::ifstream input_file(calibration_file);
    if (!input_file.is_open()) {
        std::cerr << "Ошибка: Файл калибровки " << calibration_file << " не найден." << std::endl;
        std::cerr << "Пожалуйста, сначала выполните начальную калибровку: "
                  << "./servo_calibration initial --servos <ID сервоприводов> --file " << calibration_file << std::endl;
        exit(1);
    }
    
    json all_data;
    try {
        input_file >> all_data;
    } catch (const json::exception& e) {
        std::cerr << "Ошибка: Не удалось прочитать " << calibration_file << std::endl;
        std::cerr << "Пожалуйста, сначала выполните начальную калибровку или проверьте файл." << std::endl;
        exit(1);
    }
    input_file.close();
    
    std::map<uint8_t, ServoCalibrationData> calibration_data;
    for (uint8_t servo_id : servo_ids) {
        std::string key = std::to_string(servo_id);
        if (!all_data.contains(key) || !all_data[key].contains("initial_position")) {
            std::cerr << "Ошибка: не найдены данные о начальной позиции для сервопривода " 
                      << static_cast<int>(servo_id) << " в " << calibration_file << std::endl;
            std::cerr << "Пожалуйста, сначала выполните начальную калибровку для этой ноги" << std::endl;
            exit(1);
        }
        
        calibration_data[servo_id] = ServoCalibrationData::from_json(all_data[key]);
    }
    
    return calibration_data;
}

// Разбор ID сервоприводов из строки
std::vector<uint8_t> parse_servo_ids(const std::string& servo_ids_str) {
    std::vector<uint8_t> ids;
    std::stringstream ss(servo_ids_str);
    std::string token;
    
    while (std::getline(ss, token, ',')) {
        try {
            int id = std::stoi(token);
            ids.push_back(static_cast<uint8_t>(id));
        } catch (const std::exception& e) {
            std::cerr << "Ошибка: Неверный формат ID сервоприводов" << std::endl;
            exit(1);
        }
    }
    
    if (ids.size() != 3) {
        std::cerr << "Ошибка: Необходимо указать ровно 3 ID сервоприводов" << std::endl;
        exit(1);
    }
    
    return ids;
}

// Вывод справки
void print_usage(const char* program_name) {
    std::cout << "Использование: " << program_name << " <mode> [опции]" << std::endl;
    std::cout << "\nРежимы калибровки:" << std::endl;
    std::cout << "  initial - найти и сохранить начальные положения сервоприводов" << std::endl;
    std::cout << "  limits  - найти и сохранить мин/макс положения (умный режим)" << std::endl;
    std::cout << "            Требует предварительной калибровки начальных положений" << std::endl;
    std::cout << "\nОпции:" << std::endl;
    std::cout << "  --servos ID1,ID2,ID3  - список из 3 ID сервоприводов через запятую" << std::endl;
    std::cout << "                          (по умолчанию: 1,2,3)" << std::endl;
    std::cout << "  --file PATH           - путь к JSON файлу калибровки" << std::endl;
    std::cout << "                          (по умолчанию: legs_calibration.json)" << std::endl;
    std::cout << "\nПримеры:" << std::endl;
    std::cout << "  " << program_name << " initial --servos 1,2,3" << std::endl;
    std::cout << "  " << program_name << " limits --servos 4,5,6" << std::endl;
    std::cout << "  " << program_name << " initial --servos 1,2,3 --file /path/to/calibration.json" << std::endl;
    std::cout << "  " << program_name << " limits --servos 4,5,6 --file front_left_leg.json" << std::endl;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }
    
    std::string mode = argv[1];
    std::string servo_ids_str = "1,2,3";
    std::string calibration_file = DEFAULT_CALIBRATION_FILE;
    
    // Разбор аргументов командной строки
    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--servos" && i + 1 < argc) {
            servo_ids_str = argv[++i];
        } else if (arg == "--file" && i + 1 < argc) {
            calibration_file = argv[++i];
        }
    }
    
    std::cout << "📄 Файл калибровки: " << calibration_file << std::endl;
    
    if (mode != "initial" && mode != "limits") {
        std::cerr << "Ошибка: Неверный режим. Используйте 'initial' или 'limits'" << std::endl;
        print_usage(argv[0]);
        return 1;
    }
    
    std::vector<uint8_t> servo_ids = parse_servo_ids(servo_ids_str);
    
    // Инициализация контроллера сервоприводов
    SCSCL servo_controller;
    
    if (!servo_controller.begin(BAUDRATE, DEVICENAME.c_str())) {
        std::cerr << "Ошибка: Неправильные значения частоты или порта" << std::endl;
        return 1;
    }
    
    try {
        if (mode == "initial") {
            std::cout << "\n=== Запуск калибровки начальных положений ===" << std::endl;
            auto calibration_data = calibrate_initial_positions(servo_controller, servo_ids);
            
            std::cout << "\nРезультаты калибровки начальных положений:" << std::endl;
            for (const auto& [servo_id, data] : calibration_data) {
                std::cout << "  Сервопривод " << static_cast<int>(servo_id) 
                          << ": Начальная позиция = " << data.initial_position << std::endl;
            }
            
            save_calibration_data(calibration_data, servo_ids, calibration_file);
            
        } else if (mode == "limits") {
            std::cout << "\n=== Запуск калибровки пределов (умный режим) ===" << std::endl;
            auto calibration_data = load_calibration_data(servo_ids, calibration_file);
            
            calibration_data = smart_calibration(servo_controller, servo_ids, calibration_data);
            
            // Вывод финальных результатов калибровки
            std::cout << "\n=== Результаты калибровки пределов ===" << std::endl;
            for (const auto& [servo_id, data] : calibration_data) {
                std::cout << "\nСервопривод " << static_cast<int>(servo_id) << ":" << std::endl;
                std::cout << "  Начальная позиция: " << data.initial_position << std::endl;
                std::cout << "  Мин. позиция: " << data.min_position << std::endl;
                std::cout << "  Макс. позиция: " << data.max_position << std::endl;
                std::cout << "  Диапазон: " << (data.max_position - data.min_position) << std::endl;
            }
            
            save_calibration_data(calibration_data, servo_ids, calibration_file);
        }
        
    } catch (const std::exception& e) {
        std::cerr << "Ошибка: " << e.what() << std::endl;
        
        // Отключаем крутящий момент для всех серво
        for (uint8_t servo_id : servo_ids) {
            servo_controller.EnableTorque(servo_id, 0);
        }
        servo_controller.end();
        return 1;
    }
    
    // Отключаем крутящий момент для всех серво
    for (uint8_t servo_id : servo_ids) {
        servo_controller.EnableTorque(servo_id, 0);
    }
    servo_controller.end();
    
    std::cout << "\nКалибровка завершена успешно!" << std::endl;
    
    return 0;
}

