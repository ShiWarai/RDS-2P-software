#!/usr/bin/env python3
"""
Скрипт для сохранения графа ROS2 в изображение используя rqt_graph API
Использование: python3 save_ros2_graph.py [output.png] [--format png|svg|pdf|dot|drawio] [--mode node_topic|node_node|node_topic_all]

Форматы:
  - png, svg, pdf: изображения (для просмотра)
  - dot: текстовый формат Graphviz (для редактирования текстом)
  - drawio: формат для редактирования в draw.io (https://app.diagrams.net/)
"""

import sys
import os
import argparse
import subprocess
from pathlib import Path

# Добавить путь к локальному rqt_graph в PYTHONPATH
SCRIPT_DIR = Path(__file__).parent.absolute()
RQT_GRAPH_DIR = SCRIPT_DIR / 'rqt_graph' / 'src'
if RQT_GRAPH_DIR.exists():
    sys.path.insert(0, str(RQT_GRAPH_DIR))
else:
    print(f"⚠️  Предупреждение: rqt_graph не найден в {RQT_GRAPH_DIR}")
    print("Попытка использовать системный rqt_graph...")

try:
    import rclpy
    from rclpy.node import Node
except ImportError:
    print("❌ rclpy не найден. Убедитесь, что ROS2 установлен и окружение загружено.")
    sys.exit(1)

try:
    from rqt_graph.rosgraph2_impl import Graph
    from rqt_graph.dotcode import RosGraphDotcodeGenerator, NODE_NODE_GRAPH, NODE_TOPIC_GRAPH, NODE_TOPIC_ALL_GRAPH
except ImportError as e:
    print(f"❌ Не удалось импортировать rqt_graph: {e}")
    print(f"Проверьте, что rqt_graph находится в {RQT_GRAPH_DIR}")
    sys.exit(1)

try:
    from qt_dotgraph.pydotfactory import PydotFactory
except ImportError as e:
    print(f"❌ qt_dotgraph не найден: {e}")
    print("Установите через apt: sudo apt-get install ros-humble-qt-dotgraph")
    print("Или установите python-qt-binding: pip install python-qt-binding")
    sys.exit(1)


def save_graph(output_file, format='png', graph_mode='node_topic', 
                hide_single=False, hide_dead_end=False,
                exclude_topics=None, exclude_nodes=None):
    """
    Сохранить граф ROS2 в файл
    
    Args:
        output_file: путь к выходному файлу
        format: формат вывода (png, svg, pdf, dot, drawio)
        graph_mode: режим графа (node_topic, node_node, node_topic_all)
        hide_single: скрыть топики с одним соединением
        hide_dead_end: скрыть топики только с публикаторами
        exclude_topics: список топиков для исключения (через запятую, с минусом для исключения)
        exclude_nodes: список узлов для исключения (через запятую, с минусом для исключения)
    """
    # Создать папку graphs если её нет
    graphs_dir = SCRIPT_DIR / 'graphs'
    graphs_dir.mkdir(exist_ok=True)
    
    # Если путь относительный, сохранить в graphs
    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_file = str(graphs_dir / output_path.name)
    else:
        output_file = str(output_path)
    
    print("📊 Инициализация ROS2...")
    rclpy.init()
    
    try:
        # Создать ROS2 node
        node = Node('save_ros2_graph')
        
        print("📡 Получение информации о графе...")
        # Создать Graph и обновить его
        graph = Graph(node)
        graph.set_node_stale(5.0)
        graph.update()
        
        if len(graph.nn_nodes) == 0:
            print("⚠️  Не найдено активных узлов ROS2")
            print("Убедитесь, что ROS2 система запущена")
            return 1
        
        print(f"✓ Найдено узлов: {len(graph.nn_nodes)}")
        print(f"✓ Найдено топиков: {len(graph.nt_nodes)}")
        
        # Создать генератор DOT кода
        dotcode_generator = RosGraphDotcodeGenerator(node)
        
        # Выбрать режим графа
        mode_map = {
            'node_topic': NODE_TOPIC_GRAPH,
            'node_node': NODE_NODE_GRAPH,
            'node_topic_all': NODE_TOPIC_ALL_GRAPH
        }
        selected_mode = mode_map.get(graph_mode, NODE_TOPIC_GRAPH)
        
        # Создать фабрику для генерации DOT
        dotcode_factory = PydotFactory()
        
        print("🎨 Генерация DOT кода...")
        # Сгенерировать DOT код
        # Формируем фильтры для топиков и узлов
        if exclude_topics:
            topic_filter = exclude_topics
        else:
            # По умолчанию исключаем служебные топики
            topic_filter = '-/tf,-/tf_static,-/rosout,-/parameter_events'
        
        if exclude_nodes:
            ns_filter = exclude_nodes
        else:
            # По умолчанию без фильтрации узлов (TF узлы скрываются через hide_tf_nodes)
            ns_filter = ''
        
        dotcode = dotcode_generator.generate_dotcode(
            rosgraphinst=graph,
            ns_filter=ns_filter,
            topic_filter=topic_filter,
            graph_mode=selected_mode,
            dotcode_factory=dotcode_factory,
            hide_single_connection_topics=hide_single,
            hide_dead_end_topics=hide_dead_end,
            cluster_namespaces_level=0,
            accumulate_actions=True,
            orientation='LR',
            rank='same',
            ranksep=0.2,
            rankdir='TB',  # вертикальная ориентация
            simplify=False,
            quiet=False,
            unreachable=False,
            hide_tf_nodes=True,  # Скрыть TF узлы
            group_tf_nodes=False,
            group_image_nodes=False,
            hide_dynamic_reconfigure=False
        )
        
        # Определить имя DOT файла (всегда сохранять в той же папке)
        output_path = Path(output_file)
        if format not in ['dot', 'drawio']:
            dot_file = str(output_path.with_suffix('.dot'))
        else:
            dot_file = str(output_path.with_suffix('.dot')) if format == 'drawio' else output_file
        
        # Увеличить толщину линий в DOT коде
        import re
        
        # Убрать URL из нод
        # Удаляем URL=... из определений нод
        # Паттерн для URL в начале строки с табом: \tURL=...,\n
        dotcode = re.sub(
            r'\tURL=[^,\n\]]+,\s*\n',
            '\t',
            dotcode
        )
        # Паттерн для URL в середине атрибутов: , URL=...
        dotcode = re.sub(
            r',\s*URL=[^,\n\]]+',
            '',
            dotcode
        )
        # Паттерн для URL в начале атрибутов (после имени ноды): [URL=...
        dotcode = re.sub(
            r'\[\s*URL=[^,\n\]]+,\s*',
            '[',
            dotcode
        )
        # Паттерн для URL в конце перед закрывающей скобкой: , URL=...]
        dotcode = re.sub(
            r',\s*URL=[^,\n\]]+\]',
            ']',
            dotcode
        )
        
        
        # Удалить бессвязные узлы (узлы без связей)
        # Собираем все узлы, которые используются в связях
        connected_nodes = set()
        
        # Находим все связи (edges) и извлекаем имена узлов
        edge_pattern = r'(\w+)\s*->\s*(\w+)'
        for match in re.finditer(edge_pattern, dotcode):
            source_node = match.group(1)
            target_node = match.group(2)
            connected_nodes.add(source_node)
            connected_nodes.add(target_node)
        
        # Удаляем определения узлов, которые не используются в связях
        lines = dotcode.split('\n')
        cleaned_lines = []
        skip_node_definition = False
        
        for i, line in enumerate(lines):
            # Проверяем, является ли строка определением узла (формат: node_name [attributes];)
            node_def_match = re.match(r'\t(\w+)\s*\[', line)
            if node_def_match:
                node_name = node_def_match.group(1)
                # Пропускаем узлы, которые не используются в связях
                if node_name not in connected_nodes:
                    skip_node_definition = True
                    continue
                else:
                    skip_node_definition = False
            
            # Пропускаем строки определения узла до закрывающей скобки
            if skip_node_definition:
                if '];' in line:
                    skip_node_definition = False
                continue
            
            cleaned_lines.append(line)
        
        dotcode = '\n'.join(cleaned_lines)
        
        # Увеличить penwidth для всех существующих edges (если есть)
        dotcode = re.sub(
            r'penwidth\s*=\s*[\d.]+',
            'penwidth=2.5',
            dotcode
        )
        
        # Добавляем глобальный стиль для edges с толстыми линиями
        # Ищем место после graph определения или после node определения
        if 'edge [' not in dotcode:
            # Добавляем после graph блока или после node блока
            # Сначала пробуем после graph
            if re.search(r'graph\s*\[[^\]]+\]', dotcode):
                dotcode = re.sub(
                    r'(graph\s*\[[^\]]+\]\s*;)',
                    r'\1\n\tedge [penwidth=2.5];',
                    dotcode,
                    count=1
                )
            # Если не нашли graph, добавляем после node
            elif re.search(r'node\s*\[[^\]]+\]', dotcode):
                dotcode = re.sub(
                    r'(node\s*\[[^\]]+\]\s*;)',
                    r'\1\n\tedge [penwidth=2.5];',
                    dotcode,
                    count=1
                )
            # Если ничего не нашли, добавляем после открывающей скобки
            else:
                dotcode = re.sub(
                    r'(digraph\s+\w+\s*\{)',
                    r'\1\n\tedge [penwidth=2.5];',
                    dotcode,
                    count=1
                )
        else:
            # Если стиль уже есть, добавляем penwidth если его нет
            edge_match = re.search(r'edge\s*\[([^\]]+)\]', dotcode)
            if edge_match and 'penwidth' not in edge_match.group(1):
                dotcode = re.sub(
                    r'(edge\s*\[)([^\]]+)(\])',
                    r'\1\2, penwidth=2.5\3',
                    dotcode,
                    count=1
                )
        
        # Сохранить DOT файл
        print(f"💾 Сохранение DOT файла: {dot_file}")
        with open(dot_file, 'w', encoding='utf-8') as f:
            f.write(dotcode)
        
        # Конвертировать в draw.io формат если нужно
        if format == 'drawio':
            print(f"📝 Конвертация в draw.io формат: {output_file}")
            try:
                # Проверяем наличие команды graphviz2drawio
                which_result = subprocess.run(
                    ['which', 'graphviz2drawio'],
                    capture_output=True,
                    text=True
                )
                
                if which_result.returncode == 0:
                    # Используем команду graphviz2drawio
                    # graphviz2drawio создает файл с расширением .xml по умолчанию
                    # Если указан -o, используем его
                    conv_result = subprocess.run(
                        ['graphviz2drawio', dot_file, '-o', output_file],
                        capture_output=True,
                        text=True
                    )
                    
                    if conv_result.returncode == 0:
                        print(f"✓ draw.io файл сохранен в {output_file}")
                        print(f"💡 Откройте файл в draw.io для редактирования: https://app.diagrams.net/")
                        return 0
                    else:
                        # Пробуем без -o (создаст файл с расширением .xml)
                        output_xml = str(output_path.with_suffix('.xml'))
                        conv_result = subprocess.run(
                            ['graphviz2drawio', dot_file],
                            capture_output=True,
                            text=True
                        )
                        
                        if conv_result.returncode == 0 and os.path.exists(output_xml):
                            # Переименовываем в нужное имя
                            if output_file != output_xml:
                                os.rename(output_xml, output_file)
                            print(f"✓ draw.io файл сохранен в {output_file}")
                            print(f"💡 Откройте файл в draw.io для редактирования: https://app.diagrams.net/")
                            return 0
                        else:
                            print(f"❌ Ошибка при конвертации: {conv_result.stderr}")
                            print(f"✓ DOT файл сохранен в {dot_file}")
                            return 1
                else:
                    print("❌ graphviz2drawio не найден.")
                    print("Установите одним из способов:")
                    print("  1. pip install graphviz2drawio")
                    print("  2. pipx install graphviz2drawio")
                    print(f"✓ DOT файл сохранен в {dot_file}")
                    print("💡 Вы можете конвертировать DOT в draw.io вручную:")
                    print(f"   graphviz2drawio {dot_file} -o {output_file}")
                    return 1
                    
            except Exception as e:
                print(f"❌ Ошибка при конвертации в draw.io: {e}")
                import traceback
                traceback.print_exc()
                print(f"✓ DOT файл сохранен в {dot_file}")
                return 1
        
        # Конвертировать в нужный формат
        if format not in ['dot', 'drawio']:
            print(f"🖼️  Конвертация в {format.upper()}: {output_file}")
            
            # Проверить наличие graphviz
            if not subprocess.run(['which', 'dot'], capture_output=True).returncode == 0:
                print("❌ Graphviz не установлен. Установите: sudo apt-get install graphviz")
                print(f"✓ DOT файл сохранен в {dot_file}")
                return 1
            
            # Конвертировать используя dot
            format_map = {
                'png': 'png',
                'svg': 'svg',
                'pdf': 'pdf'
            }
            dot_format = format_map.get(format, 'png')
            
            result = subprocess.run(
                ['dot', f'-T{dot_format}', dot_file, '-o', output_file],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"❌ Ошибка при конвертации: {result.stderr}")
                print(f"✓ DOT файл сохранен в {dot_file}")
                return 1
            
            # Показать размер файла
            file_size = os.path.getsize(output_file)
            file_size_mb = file_size / (1024 * 1024)
            if file_size_mb < 1:
                file_size_kb = file_size / 1024
                print(f"✓ Граф успешно сохранен в {output_file} ({file_size_kb:.1f} KB)")
            else:
                print(f"✓ Граф успешно сохранен в {output_file} ({file_size_mb:.2f} MB)")
        else:
            print(f"✓ DOT файл сохранен в {dot_file}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description='Сохранение графа ROS2 в изображение используя rqt_graph API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python3 save_ros2_graph.py output.png
  python3 save_ros2_graph.py graph.svg --format svg
  python3 save_ros2_graph.py graph.drawio --format drawio  # Для редактирования в draw.io
  python3 save_ros2_graph.py graph.png --mode node_topic_all --hide-single
  python3 save_ros2_graph.py graph.png --exclude-topics "-/tf,-/tf_static,-/rosout,-/parameter_events,-/custom_topic"
  python3 save_ros2_graph.py graph.png --exclude-nodes "-/rviz2"

Форматы для редактирования:
  - dot: текстовый формат, можно редактировать в любом редакторе
  - drawio: формат для draw.io (https://app.diagrams.net/)
            Позволяет визуально редактировать граф (перемещать узлы, изменять стили)
            Требует установки: pip install graphviz2drawio или pipx install graphviz2drawio
        """
    )
    
    parser.add_argument(
        'output',
        nargs='?',
        default='ros2_graph.png',
        help='Имя выходного файла (по умолчанию: ros2_graph.png, сохраняется в scripts/graphs/)'
    )
    
    parser.add_argument(
        '--format',
        choices=['png', 'svg', 'pdf', 'dot', 'drawio'],
        default='png',
        help='Формат вывода: png/svg/pdf (изображения), dot (текст Graphviz), drawio (для редактирования в draw.io)'
    )
    
    parser.add_argument(
        '--mode',
        choices=['node_topic', 'node_node', 'node_topic_all'],
        default='node_topic',
        help='Режим графа (по умолчанию: node_topic)'
    )
    
    parser.add_argument(
        '--hide-single',
        action='store_true',
        help='Скрыть топики с одним соединением'
    )
    
    parser.add_argument(
        '--hide-dead-end',
        action='store_true',
        help='Скрыть топики только с публикаторами'
    )
    
    parser.add_argument(
        '--exclude-topics',
        type=str,
        default=None,
        help='Топики для исключения (через запятую, формат: -/topic1,-/topic2). По умолчанию: -/tf,-/tf_static,-/rosout,-/parameter_events'
    )
    
    parser.add_argument(
        '--exclude-nodes',
        type=str,
        default=None,
        help='Узлы для исключения (через запятую, формат: -/node1,-/node2)'
    )
    
    args = parser.parse_args()
    
    # Определить формат из расширения файла, если не указан явно
    output_path = Path(args.output)
    if args.format == 'png' and output_path.suffix:
        ext_to_format = {
            '.png': 'png',
            '.svg': 'svg',
            '.pdf': 'pdf',
            '.dot': 'dot',
            '.drawio': 'drawio',
            '.xml': 'drawio'  # draw.io использует XML формат
        }
        detected_format = ext_to_format.get(output_path.suffix.lower())
        if detected_format:
            args.format = detected_format
    
    # Если формат dot или drawio, изменить расширение файла
    if args.format == 'dot' and output_path.suffix != '.dot':
        args.output = str(output_path.with_suffix('.dot'))
    elif args.format == 'drawio' and output_path.suffix not in ['.drawio', '.xml']:
        args.output = str(output_path.with_suffix('.drawio'))
    
    exit_code = save_graph(
        args.output,
        format=args.format,
        graph_mode=args.mode,
        hide_single=args.hide_single,
        hide_dead_end=args.hide_dead_end,
        exclude_topics=args.exclude_topics,
        exclude_nodes=args.exclude_nodes
    )
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

