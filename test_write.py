from datetime import datetime
from sheets.client import sheets

def main():
    if not sheets.connect():
        print("Нет подключения")
        return

    now = datetime.now()
    test = [
        f"TEST-{now.strftime('%H%M%S')}",
        now.strftime("%d.%m.%Y"),
        now.strftime("%H:%M:%S"),
        "TEST",
        "TEST GROUP",
        "TR123456",
        "",
        "",
        "",
        "Open",
        "",
        "No",
    ]
    sheets.append_case(test)
    print("Запись отправлена. Проверь лист Cases.")

if __name__ == "__main__":
    main()