"""

Conventional Color Control
for Excavator Robot

This controller is used to control the excavator robot to find the target object using the conventional color control method.

by: Naufal Mu'afi

"""

import os
import cv2
import time
import random
import numpy as np
import matplotlib.pyplot as plt
from controller import Supervisor
from typing import Any, Tuple, List


# Constants for the robot's control
MAX_MOTOR_SPEED = 0.7  # Maximum speed for the motors
LOWER_Y = -20  # Lower boundary for the y-coordinate
DISTANCE_THRESHOLD = 1.0  # Distance threshold for considering the target as "reached"

# Constants for the testing
MAX_TRIALS = 10  # Number of trials to run the testing
MAX_EPISODE_STEPS = 2000  # Maximum number of steps per trial

# Create directory for saving plots
output_dir = "test_results"
os.makedirs(output_dir, exist_ok=True)


class ColorControl(Supervisor):
    def __init__(self):
        # Initialize the supervisor class
        super().__init__()
        self.timestep = int(self.getBasicTimeStep())
        random.seed(42)

        # Get the robot node
        self.robot = self.getFromDef("EXCAVATOR")

        # Set the maximum speed for the motors and wheels
        self.max_motor_speed = MAX_MOTOR_SPEED
        self.max_wheel_speed = 5.0
        self.distance_threshold = DISTANCE_THRESHOLD

        # Get the floor node and set the arena boundaries
        self.floor = self.getFromDef("FLOOR")
        self.set_arena_boundaries()

        # Initialize the camera, motors, and sensors
        self.camera = self.init_camera()
        self.display = self.getDevice("display_1")
        self.wheel_motors, self.motors, self.sensors = self.init_motors_and_sensors()
        self.left_wheels = [self.wheel_motors["lf"], self.wheel_motors["lb"]]
        self.right_wheels = [self.wheel_motors["rf"], self.wheel_motors["rb"]]

        # Set the camera properties
        self.camera_width, self.camera_height = (
            self.camera.getWidth(),
            self.camera.getHeight(),
        )
        self.frame_area = self.camera_width * self.camera_height

        # Set the target properties
        self.center_x = self.camera_width / 2
        self.lower_y = self.camera_height + LOWER_Y
        self.target_coordinate = [self.center_x, self.lower_y]
        self.tolerance_x = 1

        # Set color range for target detection
        color_tolerance = 5
        self.color_target = np.array([46, 52, 54])
        self.lower_color = self.color_target - color_tolerance
        self.upper_color = self.color_target + color_tolerance

        # Create a window for displaying the processed image
        cv2.namedWindow("Webots Color Recognition Display", cv2.WINDOW_AUTOSIZE)

        # Set initial move
        self.initial_move = random.choice([0, 1])

        # Set the initial state
        self.state = np.zeros(4, dtype=np.int16)

        # Variables to store test results
        self.inference_times = []
        self.success_trials = 0
        self.time_to_reach_target = []
        self.distances_over_time = []
        self.total_steps = 0

    def run(self):
        while self.step(self.timestep) != -1:
            self.state, distance, centroid = self.get_observation(
                self.camera_width, self.camera_height
            )
            if self.is_done(distance, centroid):
                print("sip.")
                # self.digging_operation()

                exit(1)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    def reset(self):
        """
        Resets the simulation environment, reinitializes the robot position,
        motors, and sensors.
        """
        self.simulationReset()
        self.simulationResetPhysics()
        super().step(self.timestep)

        # Set the robot to the initial position
        self.init_pos = self.robot.getPosition()

        # Initialize the motors and sensors
        self.wheel_motors, self.motors, self.sensors = self.init_motors_and_sensors()
        self.left_wheels = [self.wheel_motors["lf"], self.wheel_motors["lb"]]
        self.right_wheels = [self.wheel_motors["rf"], self.wheel_motors["rb"]]

        super().step(self.timestep)

    def set_arena_boundaries(self):
        arena_tolerance = 1.0
        size_field = self.floor.getField("floorSize").getSFVec3f()
        x, y = size_field
        self.arena_x_max, self.arena_y_max = (
            x / 2 - arena_tolerance,
            y / 2 - arena_tolerance,
        )
        self.arena_x_min, self.arena_y_min = -self.arena_x_max, -self.arena_y_max

    def init_camera(self):
        camera = self.getDevice("cabin_camera")
        camera.enable(self.timestep)
        camera.recognitionEnable(self.timestep)

        return camera

    def init_motors_and_sensors(self):
        names = ["turret", "arm_connector", "lower_arm", "uppertolow", "scoop"]
        wheel = ["lf", "rf", "lb", "rb"]

        wheel_motors = {side: self.getDevice(f"wheel_{side}") for side in wheel}
        motors = {name: self.getDevice(f"{name}_motor") for name in names}
        sensors = {name: self.getDevice(f"{name}_sensor") for name in names}

        for motor in list(wheel_motors.values()) + list(motors.values()):
            motor.setPosition(float("inf"))
            motor.setVelocity(0.0)

        for sensor in sensors.values():
            sensor.enable(self.timestep)

        return wheel_motors, motors, sensors

    def get_observation(self, width, height):
        image = self.camera.getImage()

        # Extract RGB channels from the image
        red_channel, green_channel, blue_channel = self.extract_rgb_channels(
            image, width, height
        )
        self.img_rgb = [red_channel, green_channel, blue_channel]

        # Perform the recognition process
        coordinate, distance, centroid = self.recognition_process(
            self.img_rgb, width, height
        )

        # Get the image with the bounding box
        self._get_image_in_display(image, coordinate)

        return coordinate, distance, centroid

    def _get_image_in_display(self, img, coordinate):
        """
        Captures an image from the Webots camera and processes it for object detection.

        Returns:
            np.ndarray: The processed BGR image.
        """

        # Convert the raw image data to a NumPy array
        img_np = np.frombuffer(img, dtype=np.uint8).reshape(
            (self.camera_height, self.camera_width, 4)
        )

        # Convert BGRA to BGR for OpenCV processing
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)

        # Draw bounding box with label if state is not empty
        if np.any(coordinate != np.zeros(4, dtype=np.uint16)):
            self.draw_bounding_box(img_bgr, coordinate, "Target")

        # Display the image in the OpenCV window
        cv2.imshow("Webots Color Recognition Display", img_bgr)
        cv2.waitKey(1)

        return img_bgr

    def draw_bounding_box(self, img, cords, label):
        """
        Draws a bounding box around the detected object and labels it.

        Args:
            img (np.ndarray): The image on which to draw the bounding box.
            cords (list): Coordinates of the bounding box.
            label (str): The label of the detected object.
        """
        bb_x_min, bb_y_min, bb_x_max, bb_y_max = cords

        # Draw the bounding box
        cv2.rectangle(
            img, (bb_x_min, bb_y_min), (bb_x_max, bb_y_max), (0, 0, 255), 2
        )  # Red box

        # Get the width and height of the text box
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)

        # Draw a filled rectangle for the label background
        cv2.rectangle(
            img, (bb_x_min, bb_y_min - h - 1), (bb_x_min + w, bb_y_min), (0, 0, 255), -1
        )

        # Put the label text on the image
        cv2.putText(
            img,
            label,
            (bb_x_min, bb_y_min - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.3,
            (255, 255, 255),
            1,
        )

    def extract_rgb_channels(self, image, width, height):
        red_channel, green_channel, blue_channel = [], [], []
        for j in range(height):
            red_row, green_row, blue_row = [], [], []
            for i in range(width):
                red_row.append(self.camera.imageGetRed(image, width, i, j))
                green_row.append(self.camera.imageGetGreen(image, width, i, j))
                blue_row.append(self.camera.imageGetBlue(image, width, i, j))
            red_channel.append(red_row)
            green_channel.append(green_row)
            blue_channel.append(blue_row)
        return red_channel, green_channel, blue_channel

    def recognition_process(self, image, width, height):
        target_px, distance, centroid = 0, 300, [0, 0]
        target_x_min, target_y_min, target_x_max, target_y_max = width, height, 0, 0

        # Count the number of pixels that match the target color
        for y in range(height):
            for x in range(width):
                r, g, b = image[0][y][x], image[1][y][x], image[2][y][x]
                if (
                    self.lower_color[0] <= r <= self.upper_color[0]
                    and self.lower_color[1] <= g <= self.upper_color[1]
                    and self.lower_color[2] <= b <= self.upper_color[2]
                ):
                    target_px += 1
                    target_x_min, target_x_max = min(target_x_min, x), max(
                        target_x_max, x
                    )
                    target_y_min, target_y_max = min(target_y_min, y), max(
                        target_y_max, y
                    )

        # Calculate the target area and centroid
        if target_px == 0:
            self.search_target()

            return np.zeros(4, dtype=np.uint16), 300, [0, 0]

        # Set the new observation
        obs = np.array(
            [target_x_min, target_y_min, target_x_max, target_y_max], dtype=np.uint16
        )

        # Calculate the centroid and distance from the target
        centroid = [
            (target_x_max + target_x_min) / 2,
            (target_y_max + target_y_min) / 2,
        ]
        distance = np.sqrt(
            (centroid[0] - self.target_coordinate[0]) ** 2
            + (centroid[1] - self.target_coordinate[1]) ** 2
        )

        print(
            f"Centroid: ({centroid[0]:.2f}, {centroid[1]:.2f}); Distance: {distance:.2f}; Target size: {target_x_max - target_x_min:.1f}x{target_y_max - target_y_min:.1f}"
        )
        self.move_towards_target(centroid, distance)

        return obs, distance, centroid

    def search_target(self):
        print("No target found.")

        if self.initial_move == 0:
            self.run_wheels(self.initial_move, "left")
        elif self.initial_move == 1:
            self.run_wheels(-self.initial_move, "right")

    def move_towards_target(self, centroid, distance):
        if (distance >= self.distance_threshold) or (centroid == [None, None]):
            if centroid[0] <= self.center_x - self.tolerance_x:
                self.adjust_turret_and_wheels(direction="left")
                print("Adjusting turret and wheels to the left.")
            elif centroid[0] >= self.center_x + self.tolerance_x:
                self.adjust_turret_and_wheels(direction="right")
                print("Adjusting turret and wheels to the right.")
            else:
                self.motors["turret"].setVelocity(0.0)
                self.run_wheels(self.max_wheel_speed, "all")
                print("Moving forward.")
        else:
            self.stop_robot()

    def adjust_turret_and_wheels(self, direction):
        self.motors["turret"].setVelocity(0.0)
        if direction == "left":
            self.turn_left()
        elif direction == "right":
            self.turn_right()

    def is_done(self, distance, centroid):
        if centroid == [None, None]:
            return False

        x_threshold = [
            self.center_x - self.tolerance_x,
            self.center_x + self.tolerance_x,
        ]
        done_center_x = x_threshold[0] <= centroid[0] <= x_threshold[1]
        done_distance = distance <= self.distance_threshold

        if done_distance and done_center_x:
            print(
                f"Target achieved. Distance: {distance}; Centroid: ({centroid[0]:.2f}, {centroid[1]:.2f})"
            )
            self.stop_robot()
            return True

        return False

    def run_wheels(self, velocity, wheel="all"):
        wheels = (
            self.left_wheels + self.right_wheels
            if wheel == "all"
            else self.left_wheels if wheel == "left" else self.right_wheels
        )
        for motor in wheels:
            motor.setVelocity(velocity)

    def turn_left(self):
        self.run_wheels(-self.max_wheel_speed, "left")
        self.run_wheels(self.max_wheel_speed, "right")

    def turn_right(self):
        self.run_wheels(self.max_wheel_speed, "left")
        self.run_wheels(-self.max_wheel_speed, "right")

    def stop_robot(self):
        self.run_wheels(0.0, "all")

    def test(self):
        for trial in range(MAX_TRIALS):
            print(f"Starting trial {trial + 1}/{MAX_TRIALS}")
            start_time = time.time()
            step_count = 0
            trial_success = False
            trial_distances = []

            while self.step(self.timestep) != -1 and step_count < MAX_EPISODE_STEPS:
                step_start_time = time.time()
                coordinate, distance, centroid = self.get_observation(
                    self.camera_width, self.camera_height
                )
                trial_distances.append(distance)

                if self.is_done(distance, centroid):
                    trial_success = True
                    time_taken = time.time() - start_time
                    self.time_to_reach_target.append(time_taken)
                    print(f"Target reached in {time_taken:.2f} seconds.")
                    break

                inference_time = time.time() - step_start_time
                self.inference_times.append(inference_time)
                step_count += 1

            if trial_success:
                self.success_trials += 1
            self.distances_over_time.append(trial_distances)
            self.total_steps += step_count

            self.reset()

        self.plot_results()

    def plot_results(self):
        # Plot Inference Time
        plt.figure()
        plt.plot(self.inference_times)
        plt.title("Inference Time per Step")
        plt.xlabel("Step")
        plt.ylabel("Time (seconds)")
        plt.savefig(os.path.join(output_dir, "inference_time_per_step.png"))
        plt.show()

        # Plot Distance to Target Over Time for each trial
        for trial_num, distances in enumerate(self.distances_over_time):
            plt.figure()
            plt.plot(distances)
            plt.title(f"Distance to Target Over Time - Trial {trial_num + 1}")
            plt.xlabel("Step")
            plt.ylabel("Distance to Target")
            plt.savefig(
                os.path.join(
                    output_dir, f"distance_to_target_trial_{trial_num + 1}.png"
                )
            )
            plt.show()

        # Plot Success Rate
        success_rate = (self.success_trials / MAX_TRIALS) * 100
        print(f"Success rate: {success_rate}%")

        # Plot Time to Reach Target
        plt.figure()
        plt.hist(self.time_to_reach_target, bins=10)
        plt.title("Time to Reach Target")
        plt.xlabel("Time (seconds)")
        plt.ylabel("Number of Trials")
        plt.savefig(os.path.join(output_dir, "time_to_reach_target.png"))
        plt.show()

    # 0 is left, 1 is right
    def move_arm_connector(
        self,
        direction,
        min_position=-1.1,
        max_position=1.1,
        velocity=MAX_MOTOR_SPEED,
        toCenter=False,
    ):
        current_position = self.sensors["arm_connector"].getValue()

        if toCenter:
            tolerance = 0.001
            if current_position > tolerance or current_position < -tolerance:
                self.motors["arm_connector"].setVelocity(
                    velocity * (1 if current_position < 0 else -1)
                )
            elif current_position < tolerance or current_position > -tolerance:
                self.motors["arm_connector"].setVelocity(0.0)
        else:
            # Check if the motor is within the defined range
            if min_position <= current_position <= max_position:
                self.motors["arm_connector"].setVelocity(
                    velocity * (1 if direction == 0 else -1)
                )
            else:
                self.motors["arm_connector"].setVelocity(0.0)

    # 0 is down, 1 is up
    def move_lower_arm(
        self, direction, min_position=-0.27, max_position=0.27, velocity=MAX_MOTOR_SPEED
    ):
        current_position = self.sensors["lower_arm"].getValue()

        # Check if the motor is within the defined range
        if min_position <= current_position <= max_position:
            self.motors["lower_arm"].setVelocity(
                velocity * (1 if direction == 0 else -1)
            )
        else:
            self.motors["lower_arm"].setVelocity(0.0)

    # 0 is down, 1 is up
    def move_uppertolow(
        self, direction, min_position=-0.9, max_position=0.9, velocity=MAX_MOTOR_SPEED
    ):
        current_position = self.sensors["uppertolow"].getValue()

        # Check if the motor is within the defined range
        if min_position <= current_position <= max_position:
            self.motors["uppertolow"].setVelocity(
                velocity * (1 if direction == 0 else -1)
            )
        else:
            self.motors["uppertolow"].setVelocity(0.0)

    # 0 is inside, 1 is outside
    def move_scoop(
        self,
        direction,
        min_position=-1.1,
        max_position=1.1,
        velocity=MAX_MOTOR_SPEED + 0.5,
    ):
        current_position = self.sensors["scoop"].getValue()

        # Check if the motor is within the defined range
        if min_position <= current_position <= max_position:
            self.motors["scoop"].setVelocity(velocity * (1 if direction == 0 else -1))
        else:
            self.motors["scoop"].setVelocity(0.0)

    def digging_operation(self):
        initial_positions = {
            "scoop": self.sensors["scoop"].getValue(),
            "lower_arm": self.sensors["lower_arm"].getValue(),
            "uppertolow": self.sensors["uppertolow"].getValue(),
            "arm_connector": self.sensors["arm_connector"].getValue(),
        }

        targets = {
            "scoop": 1.0,
            "lower_arm": 0.1,
            "uppertolow": 0.45,
        }

        step = 0
        delay_start_time = None

        while True:
            current_positions = {
                "scoop": self.sensors["scoop"].getValue(),
                "lower_arm": self.sensors["lower_arm"].getValue(),
                "uppertolow": self.sensors["uppertolow"].getValue(),
            }

            if step == 0:
                # Adjust the target for uppertolow
                adjusted_targets = {
                    "scoop": -targets["scoop"],
                    "lower_arm": -targets["lower_arm"],
                    "uppertolow": -targets["uppertolow"],
                }

                self.move_scoop(
                    0,
                    min_position=initial_positions["scoop"],
                    max_position=adjusted_targets["scoop"],
                )
                self.move_lower_arm(
                    0,
                    min_position=initial_positions["lower_arm"],
                    max_position=adjusted_targets["lower_arm"],
                )
                self.move_uppertolow(1, min_position=adjusted_targets["uppertolow"])
                self.move_arm_connector(1, toCenter=True)

                print(f"Current positions: {current_positions}")
                print(f"Adjusted targets: {adjusted_targets}")

                # Check if all the joints have reached or exceeded their adjusted targets
                if all(
                    current_positions[joint] >= adjusted_targets[joint]
                    for joint in adjusted_targets
                ):
                    delay_start_time = self.getTime()
                    print("Step 0 done.")
                    step = 1

            elif step == 1:
                print("Step 1")
                if self.getTime() - delay_start_time >= 2.0:
                    step = 2

            elif step == 2:
                print("Step 2")
                # Move down
                self.move_scoop(0, max_position=targets["scoop"] - 0.5)
                self.move_lower_arm(0, max_position=targets["lower_arm"] - 0.1)
                self.move_uppertolow(0, max_position=targets["uppertolow"])
                self.move_arm_connector(1, toCenter=True)

                adjusted_targets = {
                    "lower_arm": targets["lower_arm"] - 0.1,
                    "scoop": targets["scoop"] - 0.5,
                }
                # Check if all the joints have reached or exceeded their adjusted targets
                if all(
                    current_positions[joint] <= adjusted_targets.get(joint, target)
                    for joint, target in adjusted_targets.items()
                ):
                    print("Step 2 done.")
                    delay_start_time = self.getTime()
                    step = 3

            elif step == 3:
                if self.getTime() - delay_start_time >= 1.0:
                    return [
                        initial_positions[joint]
                        for joint in [
                            "arm_connector",
                            "lower_arm",
                            "uppertolow",
                            "scoop",
                        ]
                    ]

            self.step(self.timestep)


if __name__ == "__main__":
    controller = ColorControl()
    controller.run()
