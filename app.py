import gradio as gr

def greet(name):
    return f"TTB Label Verifier — coming soon. Hello, {name}!"

demo = gr.Interface(fn=greet, inputs="text", outputs="text")

if __name__ == "__main__":
    demo.launch()
