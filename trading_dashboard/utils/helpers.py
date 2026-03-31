# trading_dashboard/utils/formatters.py

def format_currency(
    val: float,
    currency: str = "$",
    decimals: int = 2,
    show_sign: bool = False,
    html_color: bool = False
) -> str:
    """
    通貨フォーマット関数

    Args:
        val (float): 金額
        currency (str): 通貨記号
        decimals (int): 小数点桁数
        show_sign (bool): 正負符号を明示 (+/-)
        html_color (bool): HTMLで赤緑表示するか

    Returns:
        str: フォーマット済文字列
    """
    # 符号
    sign = ""
    if show_sign:
        sign = "+" if val > 0 else "-" if val < 0 else ""

    abs_val = abs(val)
    formatted = f"{currency}{abs_val:,.{decimals}f}"
    result = f"{sign}{formatted}" if show_sign else formatted

    if html_color:
        color = "green" if val > 0 else "red" if val < 0 else "black"
        result = f'<span style="color:{color}">{result}</span>'

    return result