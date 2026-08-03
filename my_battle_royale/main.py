from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
import random

app = Ursina()

# --- 1. ENVIRONMENT ---
ground = Entity(model='plane', texture='grass', collider='box', scale=(100, 1, 100))
sky = Sky()

# --- 2. USER INTERFACE (HUD) ---
score = 0
score_text = Text(text=f'SCORE: {score}', position=(-0.85, 0.45), scale=2, color=color.white)

# --- 3. PLAYER SETUP ---
player = FirstPersonController()
player.y = 2

gun = Entity(
    model='cube',
    parent=camera,
    position=(0.5, -0.25, 0.25),
    scale=(0.3, 0.2, 1),
    origin_z=-0.5,
    color=color.dark_gray
)
crosshair = Entity(parent=camera, model='quad', color=color.red, scale=0.015, position=(0,0,1))

# --- 4. ENEMY AI BOT CLASS ---
enemies = []

class Enemy(Entity):
    def __init__(self, x, z):
        # Load Jarvis's mathematically generated 3D Model
        super().__init__(
            model='assets/enemy_diamond.obj', 
            color=color.red, 
            collider='mesh',
            position=(x, 1, z),
            scale=(1.5, 1.5, 1.5)
        )
        self.health = 2
        
    def update(self):
        # AI LOGIC: The bot looks at the player's position and constantly moves forward
        self.look_at_2d(player.position, 'y')
        self.position += self.forward * time.dt * 3.5 # Bot Speed

# Spawn 10 bots randomly on the map
for i in range(10):
    enemy = Enemy(random.randint(-40, 40), random.randint(-40, 40))
    enemies.append(enemy)


# --- 5. GAME MECHANICS (SHOOTING & DAMAGE) ---
def update():
    # Gun recoil animation
    if held_keys['left mouse']: gun.position = (0.5, -0.2, 0.2)
    else: gun.position = (0.5, -0.25, 0.25)
    
def input(key):
    global score
    if key == 'left mouse down':
        # Shoot an invisible laser out of the camera
        hit_info = raycast(camera.world_position, camera.forward, distance=100)
        
        # Did we hit an Enemy Bot?
        if hit_info.hit and hit_info.entity in enemies:
            hit_info.entity.health -= 1
            hit_info.entity.blink(color.white) # Make the enemy flash when hit!
            
            # If enemy health is 0, they die!
            if hit_info.entity.health <= 0:
                destroy(hit_info.entity)
                enemies.remove(hit_info.entity)
                
                # Update Score UI
                score += 100
                score_text.text = f'SCORE: {score}'
                
                # Infinite Gameplay: Spawn a new enemy somewhere else!
                new_enemy = Enemy(random.randint(-40, 40), random.randint(-40, 40))
                enemies.append(new_enemy)

app.run()
