"""读取输入数据并汇总第二列之和。"""
INPUT = "input_data.csv"


def main():
    with open(INPUT) as f:
        rows = f.read().splitlines()
    total = sum(float(r.split(",")[1]) for r in rows)
    print(f"总计: {total}")


if __name__ == "__main__":
    main()
