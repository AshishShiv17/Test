# main.py

from Test.data import get_data
from Test.plot import plot_graph


def main():
    months, sales = get_data()
    plot_graph(months, sales)


if __name__ == "__main__":
    main()
