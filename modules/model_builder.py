import os

def generate_diamond_enemy(output_path):
    """
    Generates a 3D Diamond shape using pure math for our enemy bots.
    Vertices create the points, Faces connect them into a solid 3D mesh.
    """
    obj_data = """# Enemy Bot Diamond
v 0.0000 1.0000 0.0000
v 0.0000 -1.0000 0.0000
v 1.0000 0.0000 0.0000
v -1.0000 0.0000 0.0000
v 0.0000 0.0000 1.0000
v 0.0000 0.0000 -1.0000
f 1 3 5
f 1 5 4
f 1 4 6
f 1 6 3
f 2 5 3
f 2 4 5
f 2 6 4
f 2 3 6
"""
    with open(output_path, 'w') as f:
        f.write(obj_data)
    print(f"Generated Enemy 3D asset at {output_path}")

def generate_map_assets(project_path):
    models_dir = os.path.join(project_path, "assets")
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
        
    enemy_path = os.path.join(models_dir, "enemy_diamond.obj")
    generate_diamond_enemy(enemy_path)
    return enemy_path

if __name__ == "__main__":
    generate_map_assets("my_battle_royale")
