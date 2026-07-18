import matplotlib.pyplot as plt
import os

def generate_two_column_image(data_str, resolution_str, output_path):
    fig = plt.figure(figsize=(7, 6))
    
    data_lines = [line.strip() for line in data_str.strip().split('\n') if line.strip()]
    steps = [step.strip() for step in resolution_str.strip().split('\n') if step.strip()]
    
    # 1. Coluna Esquerda: Dados
    y_pos = 0.85
    plt.text(0.05, 0.92, "DADOS", fontsize=12, fontweight='bold', transform=fig.transFigure)
    for line in data_lines:
        plt.text(0.05, y_pos, f"${line}$", fontsize=12, family='monospace', transform=fig.transFigure)
        y_pos -= 0.07
        
    # 2. Coluna Direita: Resolução (LaTeX)
    y_pos = 0.85
    plt.text(0.45, 0.92, "RESOLUÇÃO", fontsize=12, fontweight='bold', transform=fig.transFigure)
    for index, step in enumerate(steps, start=1):
        plt.text(0.45, y_pos, f"${index}. {step}$", fontsize=13, transform=fig.transFigure)
        y_pos -= 0.08
        
    plt.axis('off')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
