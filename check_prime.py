def is_prime(n):
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True

numbers = [13969033319, 3060637, 4]
for num in numbers:
    result = is_prime(num)
    print(f"{num} 是质数吗？ {'是 ✅' if result else '否 ❌'}")
    if not result and num > 1:
        # 找一个因子
        for i in range(2, int(num**0.5)+1):
            if num % i == 0:
                print(f"  因子: {i} × {num//i}")
                break
