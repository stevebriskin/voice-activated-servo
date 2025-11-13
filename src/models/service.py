import asyncio
import subprocess
from typing import ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple

from typing_extensions import Self
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.services.generic import *
from viam.utils import ValueTypes
from viam.components.sensor import Sensor
from viam.components.servo import Servo


class Service(Generic, EasyResource):
    # To enable debug-level logging, either run viam-server with the --debug option,
    # or configure your resource/machine to display debug logs.
    MODEL: ClassVar[Model] = Model(
        ModelFamily("michaellee1019", "voice-activated-servo"), "service"
    )
    sensor: Sensor
    servo: Servo
    commands: Dict[str, List[int]]

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        """This method creates a new instance of this Generic service.
        The default implementation sets the name from the `config` parameter and then calls `reconfigure`.

        Args:
            config (ComponentConfig): The configuration for this resource
            dependencies (Mapping[ResourceName, ResourceBase]): The dependencies (both required and optional)

        Returns:
            Self: The resource
        """
        return super().new(config, dependencies)

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        """This method allows you to validate the configuration object received from the machine,
        as well as to return any required dependencies or optional dependencies based on that `config`.

        Args:
            config (ComponentConfig): The configuration for this resource

        Returns:
            Tuple[Sequence[str], Sequence[str]]: A tuple where the
                first element is a list of required dependencies and the
                second element is a list of optional dependencies
        """
        if "sensor" not in config.attributes.fields:
            raise ValueError("sensor is required")
        if "servo" not in config.attributes.fields:
            raise ValueError("servo is required")
        if "commands" not in config.attributes.fields:
            raise ValueError("commands is required")
        
        # Get the sensor and servo names
        sensor_name = config.attributes.fields["sensor"].string_value
        servo_name = config.attributes.fields["servo"].string_value
        
        # Validate commands structure
        commands = config.attributes.fields["commands"].struct_value
        
        for phrase, angles_value in commands.fields.items():
            if not isinstance(phrase, str):
                raise ValueError("command phrase must be a string")
            
            # Get the list value
            angles_list = angles_value.list_value.values
            
            if not angles_list:
                raise ValueError(f"command angles for '{phrase}' cannot be empty")
            
            for angle_value in angles_list:
                angle = angle_value.number_value
                if not (0 <= angle <= 180):
                    raise ValueError(f"command angles for '{phrase}' must be integers between 0 and 180")
        
        # Return sensor and servo as required dependencies
        return [sensor_name, servo_name], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        """This method allows you to dynamically update your service when it receives a new `config` object.

        Args:
            config (ComponentConfig): The new configuration
            dependencies (Mapping[ResourceName, ResourceBase]): Any dependencies (both required and optional)
        """
        self.logger.debug("reconfiguring...")
        
        # Get sensor and servo names
        sensor_name = config.attributes.fields["sensor"].string_value
        servo_name = config.attributes.fields["servo"].string_value
        
        # Get dependencies
        for resource_name, resource in dependencies.items():
            if resource_name.name == sensor_name:
                self.sensor = resource
                self.logger.info(f"Found sensor: {sensor_name}")
            if resource_name.name == servo_name:
                self.servo = resource
                self.logger.info(f"Found servo: {servo_name}")
        
        # Parse commands
        self.commands = {}
        commands_struct = config.attributes.fields["commands"].struct_value
        
        for phrase, angles_value in commands_struct.fields.items():
            angles = []
            for angle_value in angles_value.list_value.values:
                angles.append(int(angle_value.number_value))
            self.commands[phrase] = angles
        
        self.logger.info(f"Configured commands: {list(self.commands.keys())}")
        self.logger.debug("reconfigured")
        
        return super().reconfigure(config, dependencies)

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        
        if command.get("force_command"):
            return await self.handle_readings(command.get("force_command"))
        elif command.get("listen_for_command"):
            # Get readings from the sensor
            readings = await self.sensor.get_readings()
            return await self.handle_readings(readings.get("heard"))

    async def handle_readings(self, readings: str) -> Mapping[str, ValueTypes]:
        if readings in [None, ""]:
            return {"status": "no voice command heard"}
        else:
            commands_heard = []
            for phrase in self.commands.keys():
                if phrase.lower() in readings.lower():
                    sound_promise = self.play_sound()
                    angles = self.commands[phrase]
                    for angle in angles:
                        await self.servo.move(angle)
                        await asyncio.sleep(1)
                        self.logger.debug(f"Moving servo to angle {angle} for command {phrase}")
                    await sound_promise
                    commands_heard.append(phrase)
            if len(commands_heard) > 0:
                return {"status": "voice commands heard", "voice_commands": commands_heard, "heard": readings}
            else:
                return {"status": "no voice commands heard", "heard": readings}

    async def play_sound(self):
        try:
            # Set volume
            subprocess.run(["amixer", "-c", "UACDemoV10", "set", "PCM", "90%"], 
                         check=True, capture_output=True, text=True)
            self.logger.debug("Volume set to 90%")
            
            # Play the sound file
            subprocess.run(["aplay", "-D", "plughw:UACDemoV10", "/home/steve/sound.wav"], 
                         check=True, capture_output=True, text=True)
            self.logger.debug("Sound file played successfully")
            
            return {"status": "success", "message": "Sound played"}
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to execute sound command: {e}")
            return {"status": "error", "message": f"Command failed: {e}"}
        except Exception as e:
            self.logger.error(f"Unexpected error in sound command: {e}")
            return {"status": "error", "message": f"Unexpected error: {e}"}
