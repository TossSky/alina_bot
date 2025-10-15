"""
Export Alina Bot Database to Excel
Экспорт базы данных Алины в Excel с подробной статистикой
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


def read_table(conn, table):
    """Читает таблицу из БД с обработкой ошибок"""
    try:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)
    except Exception as e:
        print(f"⚠️  Не удалось прочитать таблицу {table}: {e}")
        return pd.DataFrame()


def parse_user_data(df_users: pd.DataFrame) -> pd.DataFrame:
    """Разворачивает JSON из столбца user_data в отдельные колонки"""
    if "user_data" not in df_users.columns or df_users.empty:
        return df_users

    def _parse(x):
        if x is None or x == "" or x == "{}":
            return {}
        try:
            return json.loads(x)
        except Exception:
            return {}

    ud = df_users["user_data"].apply(_parse)
    
    # Нормализуем JSON в колонки
    if ud.map(bool).any():
        ud_norm = pd.json_normalize(ud)
        ud_norm.columns = [f"data_{c}" for c in ud_norm.columns]
        df = pd.concat([df_users.drop(columns=["user_data"]), ud_norm], axis=1)
        return df
    else:
        return df_users.drop(columns=["user_data"])


def to_datetime_safe(series):
    """Безопасное преобразование в datetime"""
    try:
        return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None)
    except Exception:
        return pd.to_datetime(series, errors="coerce")


def build_user_stats(df_messages: pd.DataFrame) -> pd.DataFrame:
    """Строит детальную статистику по пользователям"""
    if df_messages.empty:
        return pd.DataFrame()

    df = df_messages.copy()
    
    # Приводим время
    if "timestamp" in df.columns:
        df["timestamp"] = to_datetime_safe(df["timestamp"])

    # Базовая агрегация
    stats = df.groupby("user_id", dropna=False).agg(
        total_messages=("id", "count"),
        first_message=("timestamp", "min"),
        last_message=("timestamp", "max"),
    ).reset_index()

    # Счётчики по ролям (user/assistant)
    by_role = df.pivot_table(
        index="user_id", 
        columns="role", 
        values="id", 
        aggfunc="count", 
        fill_value=0
    )
    by_role = by_role.rename_axis(None, axis=1).reset_index()
    if "user" in by_role.columns:
        by_role = by_role.rename(columns={"user": "user_messages"})
    if "assistant" in by_role.columns:
        by_role = by_role.rename(columns={"assistant": "assistant_messages"})
    
    stats = stats.merge(by_role, on="user_id", how="left")

    # Сообщения с изображениями
    if "has_image" in df.columns:
        img_count = df[df["has_image"] == True].groupby("user_id")["id"].count().reset_index(name="messages_with_images")
        stats = stats.merge(img_count, on="user_id", how="left")

    # Токены
    if "tokens_used" in df.columns:
        tokens = df.groupby("user_id")["tokens_used"].sum().reset_index(name="total_tokens")
        stats = stats.merge(tokens, on="user_id", how="left")

    # Активные дни
    if "timestamp" in df.columns and pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        active_days = df.dropna(subset=["timestamp"]).copy()
        active_days["date"] = active_days["timestamp"].dt.date
        days_active = active_days.groupby("user_id")["date"].nunique().reset_index(name="days_active")
        stats = stats.merge(days_active, on="user_id", how="left")

        # За последние 7, 30 дней
        now_utc = pd.Timestamp(datetime.utcnow())
        
        for days in [7, 30]:
            threshold = now_utc - pd.Timedelta(days=days)
            mask = df["timestamp"].notna() & (df["timestamp"] >= threshold)
            recent = df.loc[mask].groupby("user_id")["id"].count().reset_index(name=f"messages_last_{days}d")
            stats = stats.merge(recent, on="user_id", how="left")

    # Вычисляем дни с последнего сообщения
    if "last_message" in stats.columns:
        now_utc = pd.Timestamp(datetime.utcnow())
        stats["days_since_last_message"] = (now_utc - stats["last_message"]).dt.days

    # Заполним NaN нулями
    for col in stats.columns:
        if stats[col].dtype.kind in "iu":
            stats[col] = stats[col].fillna(0).astype("Int64")
        elif stats[col].dtype.kind in "f":
            stats[col] = stats[col].fillna(0)

    # Сортируем по активности
    stats = stats.sort_values("total_messages", ascending=False)
    
    return stats


def build_daily_activity(df_messages: pd.DataFrame) -> pd.DataFrame:
    """Строит статистику активности по дням"""
    if df_messages.empty or "timestamp" not in df_messages.columns:
        return pd.DataFrame()
    
    df = df_messages.copy()
    df["timestamp"] = to_datetime_safe(df["timestamp"])
    df = df.dropna(subset=["timestamp"])
    
    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour
    df["weekday"] = df["timestamp"].dt.day_name()
    
    # Агрегация по дням
    daily = df.groupby("date").agg(
        total_messages=("id", "count"),
        unique_users=("user_id", "nunique"),
    ).reset_index()
    
    # Счётчики по ролям
    by_role = df.pivot_table(
        index="date",
        columns="role",
        values="id",
        aggfunc="count",
        fill_value=0
    ).reset_index()
    
    daily = daily.merge(by_role, on="date", how="left")
    daily = daily.sort_values("date", ascending=False)
    
    return daily


def build_hourly_activity(df_messages: pd.DataFrame) -> pd.DataFrame:
    """Строит статистику активности по часам"""
    if df_messages.empty or "timestamp" not in df_messages.columns:
        return pd.DataFrame()
    
    df = df_messages.copy()
    df["timestamp"] = to_datetime_safe(df["timestamp"])
    df = df.dropna(subset=["timestamp"])
    
    df["hour"] = df["timestamp"].dt.hour
    
    hourly = df.groupby("hour").agg(
        total_messages=("id", "count"),
        unique_users=("user_id", "nunique"),
    ).reset_index()
    
    return hourly


def read_schema(conn) -> pd.DataFrame:
    """Читает схему БД"""
    rows = conn.execute(
        "SELECT name, type, sql FROM sqlite_master "
        "WHERE type IN ('table','index','view') "
        "ORDER BY type, name"
    ).fetchall()
    return pd.DataFrame(rows, columns=["name", "type", "sql"])


def autosize_columns(writer, sheet_name: str, df: pd.DataFrame, min_width=10, max_width=50):
    """Автоматически подбирает ширину колонок"""
    ws = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns, start=1):
        try:
            # Находим максимальную длину в колонке
            max_len = max(
                [len(str(col))] + 
                [len(str(v)) if pd.notna(v) else 0 for v in df[col].head(1000)]
            )
            # Устанавливаем ширину с ограничениями
            width = max(min_width, min(max_len + 2, max_width))
            col_letter = ws.cell(row=1, column=i).column_letter
            ws.column_dimensions[col_letter].width = width
        except Exception:
            pass


def create_summary_sheet(writer, stats: dict):
    """Создаёт лист с общей сводкой"""
    summary_data = {
        "Метрика": [
            "Всего пользователей",
            "Всего сообщений",
            "Сообщений от пользователей",
            "Сообщений от ассистента",
            "Сообщений с изображениями",
            "Активных пользователей (7 дней)",
            "Активных пользователей (30 дней)",
            "Дата первого сообщения",
            "Дата последнего сообщения",
            "Дата экспорта",
        ],
        "Значение": [
            stats.get("total_users", 0),
            stats.get("total_messages", 0),
            stats.get("user_messages", 0),
            stats.get("assistant_messages", 0),
            stats.get("messages_with_images", 0),
            stats.get("active_users_7d", 0),
            stats.get("active_users_30d", 0),
            stats.get("first_message", "N/A"),
            stats.get("last_message", "N/A"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ]
    }
    
    df_summary = pd.DataFrame(summary_data)
    df_summary.to_excel(writer, index=False, sheet_name="📊 Summary")
    autosize_columns(writer, "📊 Summary", df_summary)


def main():
    parser = argparse.ArgumentParser(
        description="📊 Export Alina Bot Database to Excel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python export_db.py                          # использует alina.db из текущей папки
  python export_db.py --db /path/to/alina.db  # указать путь к БД
  python export_db.py --out report.xlsx       # указать имя файла
        """
    )
    
    parser.add_argument(
        "--db", 
        default="alina.db",
        help="Путь к БД (по умолчанию: alina.db в текущей папке)"
    )
    
    parser.add_argument(
        "--out", 
        default=None,
        help="Имя выходного файла (по умолчанию: alina_export_YYYY-MM-DD.xlsx)"
    )
    
    args = parser.parse_args()
    
    # Определяем пути
    db_path = Path(args.db).resolve()
    
    if args.out:
        out_path = Path(args.out).resolve()
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = Path(f"alina_export_{date_str}.xlsx").resolve()
    
    # Проверяем существование БД
    if not db_path.exists():
        print(f"❌ Файл БД не найден: {db_path}")
        print(f"📁 Текущая директория: {Path.cwd()}")
        return 1
    
    print(f"📂 База данных: {db_path}")
    print(f"📊 Выходной файл: {out_path}")
    print(f"\n⏳ Экспортирую данные...\n")
    
    # Читаем БД
    with sqlite3.connect(str(db_path)) as conn:
        df_users_raw = read_table(conn, "users")
        df_messages = read_table(conn, "messages")
        df_schema = read_schema(conn)
    
    # Преобразования
    df_users = parse_user_data(df_users_raw.copy())
    
    if "timestamp" in df_messages.columns:
        df_messages["timestamp"] = to_datetime_safe(df_messages["timestamp"])
    
    # Создаём листы с данными
    print("📊 Создаю статистику по пользователям...")
    df_user_stats = build_user_stats(df_messages)
    
    print("📅 Создаю статистику по дням...")
    df_daily = build_daily_activity(df_messages)
    
    print("🕐 Создаю статистику по часам...")
    df_hourly = build_hourly_activity(df_messages)
    
    # Сортируем сообщения
    if "timestamp" in df_messages.columns:
        df_messages = df_messages.sort_values("timestamp", ascending=False)
    
    # Собираем общую статистику
    stats = {
        "total_users": len(df_users),
        "total_messages": len(df_messages),
        "user_messages": len(df_messages[df_messages["role"] == "user"]) if "role" in df_messages.columns else 0,
        "assistant_messages": len(df_messages[df_messages["role"] == "assistant"]) if "role" in df_messages.columns else 0,
        "messages_with_images": len(df_messages[df_messages.get("has_image", False) == True]) if "has_image" in df_messages.columns else 0,
    }
    
    # Активные пользователи
    if not df_messages.empty and "timestamp" in df_messages.columns:
        now_utc = pd.Timestamp(datetime.utcnow())
        
        last_7d = df_messages[df_messages["timestamp"] >= now_utc - pd.Timedelta(days=7)]
        stats["active_users_7d"] = last_7d["user_id"].nunique() if not last_7d.empty else 0
        
        last_30d = df_messages[df_messages["timestamp"] >= now_utc - pd.Timedelta(days=30)]
        stats["active_users_30d"] = last_30d["user_id"].nunique() if not last_30d.empty else 0
        
        stats["first_message"] = df_messages["timestamp"].min().strftime("%Y-%m-%d %H:%M") if not df_messages.empty else "N/A"
        stats["last_message"] = df_messages["timestamp"].max().strftime("%Y-%m-%d %H:%M") if not df_messages.empty else "N/A"
    
    # Записываем в Excel
    print(f"\n💾 Сохраняю в Excel...")
    
    with pd.ExcelWriter(
        out_path, 
        engine="openpyxl",
        datetime_format="yyyy-mm-dd hh:mm:ss"
    ) as writer:
        
        # Сводка
        create_summary_sheet(writer, stats)
        
        # Основные листы
        sheets = [
            ("👥 Users", df_users),
            ("📊 User Stats", df_user_stats),
            ("💬 Messages", df_messages),
            ("📅 Daily Activity", df_daily),
            ("🕐 Hourly Activity", df_hourly),
            ("🗄️ Schema", df_schema),
        ]
        
        for name, df in sheets:
            if not df.empty:
                df.to_excel(writer, index=False, sheet_name=name)
                autosize_columns(writer, name, df)
                print(f"   ✓ {name}: {len(df)} записей")
    
    print(f"\n✅ Экспорт завершён!")
    print(f"📁 Файл: {out_path}")
    print(f"📊 Размер: {out_path.stat().st_size / 1024:.1f} KB")
    
    # Выводим краткую статистику
    print(f"\n📈 Краткая статистика:")
    print(f"   👥 Пользователей: {stats['total_users']}")
    print(f"   💬 Сообщений: {stats['total_messages']}")
    print(f"   🔥 Активных (7д): {stats.get('active_users_7d', 0)}")
    print(f"   📸 С изображениями: {stats['messages_with_images']}")
    
    return 0


if __name__ == "__main__":
    exit(main())
