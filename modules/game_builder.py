import os

def scaffold_3d_game(project_name="my_shooter_game"):
    """
    Instructs Jarvis to build a boilerplate 3D First Person game 
    using the Ursina engine in Python.
    """
    if not os.path.exists(project_name):
        os.makedirs(project_name)

    game_code = """from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController

# Initialize the 3D Engine
app = Ursina()

# Create the ground / map
ground = Entity(
    model='plane',
    texture='grass',
    collider='box',
    scale=(100, 1, 100)
)

# Add some obstacles/buildings to simulate a battle royale map
import random
for i in range(20):
    Entity(
        model='cube',
        color=color.dark_gray,
        collider='box',
        position=(random.randint(-40, 40), 1, random.randint(-40, 40)),
        scale=(random.randint(2, 5), random.randint(2, 10), random.randint(2, 5))
    )

# Add the sky
sky = Sky()

# Create the First Person Player
player = FirstPersonController()
player.y = 2

# Add a basic "gun" mechanic
gun = Entity(
    model='cube',
    parent=camera,
    position=(0.5, -0.25, 0.25),
    scale=(0.3, 0.2, 1),
    origin_z=-0.5,
    color=color.black,
    on_cooldown=False
)

def update():
    # Simple shooting animation
    if held_keys['left mouse']:
        gun.position = (0.5, -0.2, 0.2)
    else:
        gun.position = (0.5, -0.25, 0.25)

app.run()
"""

    file_path = os.path.join(project_name, "main.py")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(game_code)
        
    # Write a requirements file for the game
    with open(os.path.join(project_name, "requirements.txt"), "w") as f:
        f.write("ursina==6.1.1\n")

    return f"Success! 3D game scaffolded at ./{project_name}/main.py"

if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "battle_royale_beta"
    print(scaffold_3d_game(name))
