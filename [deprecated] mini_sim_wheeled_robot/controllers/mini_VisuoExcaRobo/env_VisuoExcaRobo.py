import sys
from enum import Enum
from controller import Supervisor, Display
from typing import Any, Tuple, List

try:
    import random
    import numpy as np
    import gymnasium as gym
    from gymnasium import Env, spaces
    from gymnasium.envs.registration import EnvSpec, register
except ImportError:
    sys.exit(
        "Please make sure you have all dependencies installed. "
        "Run: `pip install numpy gymnasium stable_baselines3`"
    )


MAX_EPISODE_STEPS = 1500


class mini_VisuoExcaRobo(Supervisor, Env):
    def __init__(self, max_episode_steps: int = MAX_EPISODE_STEPS) -> None:
        # Initialize the Robot class
        super().__init__()
        random.seed(42)

        # register the Environment
        self.spec: EnvSpec = EnvSpec(
            id="mini_VisuoExcaRobo-v1", max_episode_steps=max_episode_steps
        )

        # set the max_speed of the motors
        self.max_speed = 4.0

        # set the threshold of the target area
        self.target_threshold = 0.35

        # get the robot node
        self.robot = self.getFromDef("ROBOT")

        # get the floor node
        arena_tolerance = 0.05
        self.floor = self.getFromDef("FLOOR")
        size_field = self.floor.getField("floorSize").getSFVec3f()

        x, y = size_field
        self.x_max, self.y_max = x / 2 - arena_tolerance, y / 2 - arena_tolerance
        self.x_min, self.y_min = -self.x_max, -self.y_max

        # get the camera devices
        self.camera = self.getDevice("camera")

        # set the action spaces: 0 = left, 1 = right
        self.action_space = spaces.Box(low=-1, high=1, shape=(2,), dtype=np.float32)

        # set the observation space: (channels, camera_height, camera_width)
        self.observation_space = spaces.Box(
            low=0,
            high=255,
            shape=(3, self.camera.getHeight(), self.camera.getWidth()),
            dtype=np.uint8,
        )

        # environment specification
        self.state = None
        self.display: Any = None
        self.motors: List[Any] = []
        self.__timestep: int = int(self.getBasicTimeStep())

    def reset(self, seed: Any = None, options: Any = None):
        # Reset the simulation
        self.simulationResetPhysics()
        self.simulationReset()
        super().step(self.__timestep)

        # get the robot initial position
        self.init_pos = self.robot.getPosition()

        # get the camera devices
        self.camera = self.getDevice("camera")
        self.camera.enable(self.__timestep)
        self.camera.recognitionEnable(self.__timestep)
        self.camera.enableRecognitionSegmentation()

        # Get the display device
        self.display = self.getDevice("segmented image display")

        # Get the left and right wheel motors
        self.motors = []
        for name in ["left wheel motor", "right wheel motor"]:
            motor = self.getDevice(name)
            self.motors.append(motor)
            motor.setPosition(float("inf"))
            motor.setVelocity(0.0)

        # internal state
        super().step(self.__timestep)

        # initial state
        self.state = np.zeros(
            (3, self.camera.getHeight(), self.camera.getWidth()), dtype=np.uint8
        )

        # info
        info: dict = {}

        return self.state, info

    def step(self, action):
        width = self.camera.getWidth()
        height = self.camera.getHeight()
        frame_area = width * height

        # Initialize variables for tracking progress
        previous_target_area = self.calculate_color_target_area(
            self.state, width, height, frame_area
        )

        # Rescale actions from [-1, 1] to [-self.max_spped, self.max_spped]
        scaled_action = action * self.max_speed

        # perform a continuous action
        self.motors[0].setVelocity(scaled_action[0])
        self.motors[1].setVelocity(scaled_action[1])

        # Get the new state
        super().step(self.__timestep)

        # get the new state
        self.state, target_area = self.get_and_display_obs(width, height, frame_area)

        # Reward for reducing the distance to the target
        area_increase = target_area - previous_target_area

        # More impatient reward function
        reward = area_increase * 100  # Reward based on the area increase

        if target_area > previous_target_area:
            reward += 50  # Additional reward for progress towards target
        else:
            reward -= 50  # Penalty for moving away from the target or stagnating

        # get the current position of the robot
        pos = self.robot.getPosition()

        # calculate the distance between the initial and current position
        distance = (
            (pos[0] - self.init_pos[0]) ** 2 + (pos[1] - self.init_pos[1]) ** 2
        ) ** 0.5

        # Add a time penalty to encourage quicker completion
        reward -= 1  # Time penalty for each step taken

        # Check if the episode is done
        if target_area >= self.target_threshold:
            reward += 10000
            done = True
        elif distance >= 0.6:
            reward -= 10000
            done = True
        else:
            done = False

        # Arena Boundaries Check
        if (
            pos[0] == self.x_min
            or pos[0] == self.x_max
            or pos[1] == self.y_min
            or pos[1] == self.y_max
        ):
            done = True
            reward -= 10000

        # info dictionary can be used for debugging or additional info
        info = {
            "robot_position": pos,
            "distance": distance,
            "target_area": target_area,
        }

        return self.state, reward, done, False, info

    def render(self, mode: str = "human") -> None:
        pass

    def get_and_display_obs(self, width, height, frame_area):
        red_channel, green_channel, blue_channel = [], [], []

        if (
            self.camera.isRecognitionSegmentationEnabled()
            and self.camera.getRecognitionSamplingPeriod() > 0
        ):
            image = self.camera.getImage()
            objects = self.camera.getRecognitionObjects()
            data = self.camera.getRecognitionSegmentationImage()

            if data:
                # Loop through each pixel in the image
                for j in range(height):
                    red_row, green_row, blue_row = [], [], []

                    for i in range(width):
                        # Get the RGB values for the pixel (i, j)
                        red = self.camera.imageGetRed(image, width, i, j)
                        green = self.camera.imageGetGreen(image, width, i, j)
                        blue = self.camera.imageGetBlue(image, width, i, j)

                        # Append the RGB values as a tuple to the row
                        red_row.append(red)
                        green_row.append(green)
                        blue_row.append(blue)

                    # Append the row to the pixels list
                    red_channel.append(red_row)
                    green_channel.append(green_row)
                    blue_channel.append(blue_row)

                # new state
                self.state = np.array(
                    [red_channel, green_channel, blue_channel], dtype=np.uint8
                )

                self.display_segmented_image(data, width, height)

                # calculate the target area
                target_area = self.calculate_color_target_area(
                    self.state, width, height, frame_area
                )

        return self.state, target_area

    def display_segmented_image(self, data, width, height):
        segmented_image = self.display.imageNew(data, Display.BGRA, width, height)
        self.display.imagePaste(segmented_image, 0, 0, False)
        self.display.imageDelete(segmented_image)

    def calculate_color_target_area(self, image, width, height, frame_area):
        target_px = 0

        for y in range(height):
            for x in range(width):
                # get the RGB values for the pixel (x, y)
                r = image[0][y][x]  # Red channel
                g = image[1][y][x]  # Green channel
                b = image[2][y][x]  # Blue channel

                # check if the pixel matches the target color i.e. red color
                if r == 170 and g == 0 and b == 0:
                    target_px += 1

        target_area = target_px / frame_area

        return target_area


# register the environment
register(
    id="mini_VisuoExcaRobo-v1",
    entry_point=lambda: mini_VisuoExcaRobo(),
    max_episode_steps=MAX_EPISODE_STEPS,
)
