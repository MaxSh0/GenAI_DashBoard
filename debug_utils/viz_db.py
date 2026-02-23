from sqlalchemy import inspect
from modules.db_manager import engine


def print_db_structure():
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if not tables:
        print("📭 База данных пуста. Таблицы еще не созданы.")
        return

    print("=" * 50)
    print("📊 СТРУКТУРА POSTGRESQL (GenAI Dashboard)")
    print("=" * 50)

    for table_name in tables:
        print(f"\n🔹 ТАБЛИЦА: {table_name.upper()}")

        # 1. Вывод колонок
        columns = inspector.get_columns(table_name)
        print("  📝 Колонки:")
        for column in columns:
            name = column['name']
            ctype = column['type']
            pk = " [🔑 PK]" if column.get('primary_key') else ""
            nullable = "" if column.get('nullable') else " [NOT NULL]"
            print(f"    - {name:<15} | {str(ctype):<12} {pk}{nullable}")

        # 2. Вывод связей (Foreign Keys)
        fks = inspector.get_foreign_keys(table_name)
        if fks:
            print("  🔗 Связи (Foreign Keys):")
            for fk in fks:
                # Показываем какую колонку текущей таблицы привязываем к какой внешней
                constrained_cols = ", ".join(fk['constrained_columns'])
                referred_table = fk['referred_table']
                referred_cols = ", ".join(fk['referred_columns'])
                print(f"    - ({constrained_cols})  --->  {referred_table}({referred_cols})")

        print("-" * 30)


if __name__ == "__main__":
    try:
        print_db_structure()
    except Exception as e:
        print(f"🔥 Ошибка при чтении БД: {e}")