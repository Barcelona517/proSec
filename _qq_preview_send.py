from qq_tools import QQAutomation


qq = QQAutomation()
print("attach:", qq.attach_or_launch())
preview = qq.preview_send_targets("好望角 03.04")
print("preview:", preview)
if preview.get("can_send_safely"):
    print(
        "send:",
        qq.send_message(
            "好望角 03.04",
            "嘿嘿好玩",
            confirmed_name=preview.get("selected_name", ""),
        ),
    )
