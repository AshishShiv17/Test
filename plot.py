# plot.py

import matplotlib.pyplot as plt


def plot_graph(x, y):
    plt.figure(figsize=(8, 5))
    plt.plot(x, y, marker="o", linewidth=2)

    plt.title("Monthly Sales")
    plt.xlabel("Month")
    plt.ylabel("Sales")
    plt.grid(True)

    plt.show()
