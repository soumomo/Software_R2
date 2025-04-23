import asyncio
import websockets
import json
import math

async def run_drone():
    server_addr = "ws://localhost:8765"
    print("Connecting...")
    
    async with websockets.connect(server_addr) as ws:
        print("Connected!")
        
        try:
            init_resp_str = await ws.recv()
            init_data = json.loads(init_resp_str)
            print(f"Server: {init_data['message']}") # note: assumes 'message' key exists
        except Exception as e:
            print(f"Error getting welcome: {e}")
            return 

        init_cmd = {"speed": 0, "altitude": 1, "movement": "fwd"} 
        print(f"Sending first command: {init_cmd}")
        try:
            await ws.send(json.dumps(init_cmd))
        except Exception as e:
             print(f"Error sending first command: {e}")
             return 

        print("Starting loop...")
        cruise_dir = 1 # cruise altitude direction toggle
        move_dir = "fwd" # current movement direction

        while True:
            try:
                resp_str = await ws.recv()
                resp_data = json.loads(resp_str)

                cmd = {} # reset command for this cycle

                if resp_data["status"] == "success": # note: assumes 'status' key exists
                    tele_str = resp_data["telemetry"]
                    
                    try:
                        parts = tele_str.split("-")
                        tele_data = {}
                        i = 0
                        while i < len(parts):
                            if parts[i] == 'Y' and i + 1 < len(parts):
                                tele_data['Y'] = float(parts[i+1])
                                i += 2
                            elif parts[i] == 'BAT' and i + 1 < len(parts):
                                tele_data['BAT'] = float(parts[i+1])
                                i += 2
                            elif parts[i] == 'SENS' and i + 1 < len(parts):
                                tele_data['SENS'] = parts[i+1].strip()
                                i += 2
                            elif parts[i] == 'X' and i + 1 < len(parts):
                                tele_data['X'] = float(parts[i+1])
                                i += 2
                            elif parts[i] == 'GYR' and i + 1 < len(parts):
                                gyr_str = parts[i+1].strip() 
                                if gyr_str.startswith('[') and gyr_str.endswith(']'):
                                    values_str = gyr_str[1:-1].split(',') 
                                    if len(values_str) == 3:
                                        try:
                                            tele_data['GYR'] = [float(v.strip()) for v in values_str]
                                        except ValueError: # handle potential conversion errors
                                            tele_data['GYR'] = [0.0, 0.0, 0.0] # default value
                                    else:
                                        tele_data['GYR'] = [0.0, 0.0, 0.0] # default if not 3 values
                                else:
                                     tele_data['GYR'] = [0.0, 0.0, 0.0] # default if format wrong
                                i += 2 
                            elif parts[i] == 'WIND' and i + 1 < len(parts):
                                try: 
                                    tele_data['WIND'] = float(parts[i+1])
                                except ValueError:
                                    tele_data['WIND'] = 0.0
                                i += 2
                            elif parts[i] == 'DUST' and i + 1 < len(parts):
                                try: 
                                    tele_data['DUST'] = float(parts[i+1])
                                except ValueError:
                                    tele_data['DUST'] = 0.0
                                i += 2
                            else:
                                i += 1 # move to next part if unrecognized

                        keys_needed = ('Y', 'BAT', 'SENS', 'X', 'GYR') 
                        if not all(k in tele_data for k in keys_needed):
                            print(f"Missing keys. Got: {tele_data.keys()}")
                            # let it potentially fail below if keys are missing

                        Y = tele_data['Y']
                        battery = tele_data['BAT']
                        sensor_status = tele_data['SENS']
                        X = tele_data['X'] # note: assumes 'x' key exists
                        gyro = tele_data['GYR'] # note: assumes 'gyr' key exists
                        wind = tele_data.get('WIND', 0.0) # use .get for optional fields
                        dust = tele_data.get('DUST', 0.0) # use .get for optional fields

                        print(f"Data: Y={Y}, Bat={battery}%, Status={sensor_status}, X={X}")

                        if battery < 5.0: 
                            print("Landing!")
                            cmd = {"speed": 0, "altitude": -1, "movement": "fwd"}
                            if Y < 0.5: 
                                print("Landed.")
                                cmd = {"speed": 0, "altitude": 0, "movement": "fwd"}
                                # break # optional: stop after landing

                        elif sensor_status == "RED" and Y >= 15: # simulator crashes if red and y > 3
                            print("Emergency Down (RED)!")
                            cmd = {"speed": 0, "altitude": -2, "movement": "fwd"}
                        elif sensor_status == "YELLOW":
                            safe_alt_yellow = 2.0 # target safe altitude for yellow
                            if Y > safe_alt_yellow:
                                print(f"Caution (YELLOW)! Descending FASTER to safe altitude Y={safe_alt_yellow}")
                                cmd = {"speed": 1, "altitude": -2, "movement": move_dir} # descend quickly
                            else:
                                print(f"Caution (YELLOW)! Holding safe altitude at Y={Y}")
                                cmd = {"speed": 1, "altitude": 0, "movement": move_dir} # hold altitude
                        elif sensor_status == "GREEN":
                            tilt_limit = 40.0 # tilt limit (degrees)
                            max_tilt_val = max(abs(gyro[0]), abs(gyro[2])) # check pitch/roll tilt
                            if max_tilt_val > tilt_limit:
                                 print(f"Tilt High! ({max_tilt_val:.1f}) Stabilizing.")
                                 cmd = {"speed": 0, "altitude": 0, "movement": "fwd"} # stop and stabilize

                            elif abs(X) > 99900: # check if near world boundary
                                 print(f"Range Limit! X={X}. Reversing.")
                                 move_dir = "rev" if move_dir == "fwd" else "fwd" # reverse direction
                                 cmd = {"speed": 1, "altitude": cruise_dir, "movement": move_dir}
                                 cruise_dir *= -1 # flip cruise altitude direction

                            elif Y <= 0: # if on the ground
                                print("Taking off!")
                                cmd = {"speed": 0, "altitude": 1, "movement": "fwd"} # initial climb

                            else: # normal flight logic
                                target_alt = 980 # high altitude target
                                if Y < target_alt:
                                    print(f"Climbing to {target_alt}")
                                    cmd = {"speed": 1, "altitude": 2, "movement": move_dir} # climb command
                                    cruise_dir = 1 # reset cruise direction for next time
                                else: # reached target altitude
                                    print(f"Cruising High")
                                    cmd = {"speed": 1, "altitude": cruise_dir, "movement": move_dir} # cruise command (slight up/down)
                                    cruise_dir *= -1 # alternate cruise altitude

                        if 5.0 <= battery < 10.0: # check for low battery warning threshold
                            print(f"Low Battery Warning: {battery}%")

                    except Exception as e: # catch potential errors during telemetry processing
                        print(f"Error parsing telemetry: {e}")
                        print(f"String: {tele_str}")
                        cmd = {"speed": 0, "altitude": 0, "movement": "fwd"} # failsafe command

                elif resp_data["status"] == "crashed": # note: assumes 'status'/'message' keys exist
                    print(f"CRASHED: {resp_data['message']}")
                    break # exit loop on crash
                else:
                    print(f"Unknown status: {resp_data.get('status')}") # handle unexpected status

                if cmd: # check if a command was determined this cycle
                    print(f"Sending: {cmd}")
                    await ws.send(json.dumps(cmd))
                else:
                    # if no specific command needed (e.g., already landed and break commented out), just wait.
                    print("Waiting...")

                await asyncio.sleep(1) # wait 1 second before next cycle

            except websockets.exceptions.ConnectionClosed as e:
                print(f"Connection closed: {e}")
                break # exit loop if connection lost
            except Exception as e:
                print(f"Loop error: {e}")
                break # exit loop on other errors

    print("Exiting.")

asyncio.run(run_drone())
