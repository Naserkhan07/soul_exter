import os

def scaffold_data_analysis():
    """
    Writes a pandas/matplotlib script to analyze a dataset and draw a graph.
    """
    project_name = "data_analysis"
    if not os.path.exists(project_name):
        os.makedirs(project_name)

    script_code = """import pandas as pd
import matplotlib.pyplot as plt

# 1. Generate some mock sales data
data = {
    'Month': ['Jan', 'Feb', 'Mar', 'Apr', 'May'],
    'Revenue': [15000, 22000, 18000, 29000, 34000]
}
df = pd.DataFrame(data)

# 2. Analyze
average_revenue = df['Revenue'].mean()
print(f"Average Revenue: ${average_revenue:,.2f}")

# 3. Graph
plt.figure(figsize=(8, 5))
plt.plot(df['Month'], df['Revenue'], marker='o', color='blue', linewidth=2)
plt.title('Jarvis Automated Revenue Analysis')
plt.xlabel('Month')
plt.ylabel('Revenue ($)')
plt.grid(True)
plt.savefig('revenue_chart.png')
print("Graph saved as revenue_chart.png")
"""
    file_path = os.path.join(project_name, "analyze.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(script_code)
        
    return f"📊 [DATA SCIENTIST] I have written the data analysis script at {file_path}. It uses pandas to calculate stats and matplotlib to draw charts!"

if __name__ == "__main__":
    print(scaffold_data_analysis())
