# Script for controlling the whole setup automagically
import ThorlabsCam as TC
import SLM
import ThorlabsMotor as TM
import TemperatureControllerTED4015
import find_particle_threshold as fpt
import read_dict_from_file as rdff
import CameraControls
from common_experiment_parameters import get_default_c_p
from instrumental import u
import matplotlib.pyplot as plt
import numpy as np
import threading, time, cv2, queue, copy, sys, tkinter, os, pickle
from tkinter import messagebox
from tkinter import filedialog as fd
from functools import partial
from datetime import datetime
from cv2 import VideoWriter, VideoWriter_fourcc
from tkinter import *  # TODO Should avoid this type of import statements.
import PIL.Image, PIL.ImageTk
from pypylon import pylon

def terminate_threads():
    '''
    Function for terminating all threads.

    Returns
    -------
    None.

    '''
    c_p['program_running'] = False
    c_p['motor_running'] = False
    c_p['tracking_on'] = False
    time.sleep(1)
    global thread_list
    for thread in thread_list:
        thread.join()
    for thread in thread_list:
        del thread


def start_threads(c_p, thread_list, cam=True, motor_x=False, motor_y=False, motor_z=False,
                    slm=False, tracking=False, isaac=False, temp=False):
    # TODO include these parameters in c_p
    """
    Function for starting all the threads, should only be called once!
    """

    if cam:
        camera_thread = CameraControls.CameraThread(1, 'Thread-camera',c_p=c_p)
        camera_thread.start()
        thread_list.append(camera_thread)
        print('Camera thread started')

    if motor_x:
        try:
            motor_X_thread = TM.MotorThread(2,'Thread-motorX',0,c_p)
            motor_X_thread.start()
            thread_list.append(motor_X_thread)
            print('Motor x thread started')
        except:
            print('Could not start motor x thread')

    if motor_y:
        try:
            motor_Y_thread = TM.MotorThread(3,'Thread-motorY',1,c_p)
            motor_Y_thread.start()
            thread_list.append(motor_Y_thread)
            print('Motor y thread started')
        except:
            print('Could not start motor y thread')

    if motor_z:
        try:
            z_thread = TM.z_movement_thread(4, 'z-thread',serial_no=c_p['serial_nums_motors'][2],channel=c_p['channel'],c_p=c_p)
            z_thread.start()
            thread_list.append(z_thread)
            print('Motor z thread started')
        except:
            print('Could not start motor z thread')

    if slm:
        slm_thread =CreatePhasemaskThread(5,'Thread-SLM')
        slm_thread.start()
        thread_list.append(slm_thread)
        print('SLM thread started')

    if tracking:
        tracking_thread = ExperimentControlThread(6,'Tracker_thread')
        tracking_thread.start()
        thread_list.append(tracking_thread)
        print('Tracking thread started')

    if temp:

        try:
            temperature_controller = TemperatureControllerTED4015.TED4015()
        except:
            temperature_controller = None
            print('problem connecting to temperature controller')
        temperature_thread = TemperatureThread(7,'Temperature_thread',temperature_controller=temperature_controller)
        temperature_thread.start()
        thread_list.append(temperature_thread)
        print('Temperature thread started')


class UserInterface:

    def __init__(self, window, window_title, c_p, thread_list, use_SLM = False,
                cam=True, motor_x=False, motor_y=False, motor_z=False, slm=False,
                tracking=False, isaac=False, temp=False):
        self.window = window
        self.window.title(window_title)

        # Create a canvas that can fit the above video source size
        self.canvas_width = 1200
        self.canvas_height = 1000

        self.mini_canvas_width = 240
        self.mini_canvas_height = 200

        self.canvas = tkinter.Canvas(
            window, width=self.canvas_width, height=self.canvas_height)
        self.canvas.place(x=0, y=0)

        self.mini_canvas = tkinter.Canvas(
            window, width=self.mini_canvas_width, height=self.mini_canvas_height)
        self.mini_canvas.place(x=1200, y=800)
        self.mini_image = np.zeros((200,240,3))
        # Button that lets the user take a snapshot
        self.btn_snapshot = tkinter.Button(
            window, text="Snapshot", command=snapshot)
        self.btn_snapshot.place(x=1300, y=0)
        self.create_buttons(self.window)
        self.window.geometry('1700x1000')
        # After it is called once, the update method will be automatically
        # called every delay milliseconds
        self.delay = 100#50
        if use_SLM:
            self.create_SLM_window(SLM_window)
        self.create_indicators()
        self.update()
        start_threads(c_p, thread_list, cam=cam, motor_x=motor_x, motor_y=motor_y, motor_z=motor_z,
                            slm=slm, tracking=tracking, isaac=isaac, temp=temp)

        self.window.mainloop()

    def __del__(self):
        # Close the program
        terminate_threads()
        c_p['program_running'] = False
        c_p['motor_running'] = False
        c_p['tracking_on'] = False

    def read_experiment_dictionary(self):
        global c_p
        filepath = fd.askopenfilename()
        # TODO make it so that we can handle exceptions from the file better here.
        # Bring up a confirmation menu for the schedule perhaps?
        experiment_list = rdff.ReadFileToExperimentList(filepath)
        if experiment_list is not None and len(experiment_list) > 0:
            c_p['experiment_schedule'] = experiment_list
            print('Starting the following experiment. \n', experiment_list)
            # Reset experiment progress
            if c_p['tracking_on']:
                c_p['tracking_on'] = False
                time.sleep(0.5)
                c_p['experiment_progress'] = 0
                time.sleep(0.2)
                c_p['tracking_on'] = True
            else:
                c_p['experiment_progress'] = 0
            c_p['nbr_experiments'] = len(c_p['experiment_schedule'])
            # Update recording path
            name = filepath[filepath.rfind('/')+1:filepath.rfind('.')]
            c_p['recording_path'] = get_save_path(extension_path='_'+name)
        else:
            print('Invalid or empty file.')

    def create_trap_image(self):
        global c_p
        trap_x = c_p['traps_absolute_pos'][0]
        trap_y = c_p['traps_absolute_pos'][1]
        particle_x = c_p['particle_centers'][0]
        particle_y = c_p['particle_centers'][1]
        AOI = c_p['AOI']
        # Define new mini-image
        mini_image = np.zeros((200,240,3))
        scale_factor = 5

        l = int(round(AOI[2]/scale_factor))  # left
        r = int(round(AOI[3]/scale_factor))  # right
        u = int(round(AOI[0]/scale_factor))  # up
        d = int(round(AOI[1]/scale_factor))  # down

        # Draw the traps
        if len(trap_x) > 0 and len(trap_x) == len(trap_y):
            for x, y in zip(trap_x, trap_y):
                # Round down and recalculate
                x = int(round(x/scale_factor))
                y = int(round(y/scale_factor))

                if 1 <= x <= 239 and 1 <= y <= 199:
                    mini_image[(y-1):(y+2),(x-1):(x+2),0] = 255

        # Draw the particles
        if  len(particle_x) > 0 and len(particle_x) == len(particle_y):
            for x, y in zip(particle_x, particle_y):
                # Round down and recalculate
                x = int(round(x/scale_factor + u))
                y = int(round(y/scale_factor + l))
                if 1 <= x <= 239 and 1 <= y <= 199:
                    mini_image[y-1:y+2,x-1:x+2,2] = 255

        # Draw the AOI
        try:
            mini_image[l,u:d,1:2] = 255  # Left edge
            mini_image[l:r,u,1:2] = 255  # Upper edge
            mini_image[r,u:d,1:2] = 255  # Right edge
            mini_image[l:r,d,1:2] = 255  # Bottom edge
        except:
            mini_image[0,0:-1,1:2] = 255  # Left edge
            mini_image[0:-1,0,1:2] = 255  # Upper edge
            mini_image[-1,0:-1,1:2] = 255  # Right edge
            mini_image[0:-1,-1,1:2] = 255  # Bottom edge

        self.mini_image = mini_image.astype('uint8')

    def create_buttons(self,top=None):
        '''
        This function generates all the buttons for the interface along with
        the other control elementsn such as entry boxes.
        '''
        global c_p
        if top is None:
            top = self.window

        def get_y_separation(start=50, distance=40):
            # Simple generator to avoid printing all the y-positions of the
            # buttons
            index = 0
            while True:
                yield start + (distance * index)
                index += 1

        def home_z_command():
            c_p['return_z_home'] = not c_p['return_z_home']

        # TODO add home z button
        # TODO: Check if we can change colors of buttons by making buttons part of
        # object.

        up_button = tkinter.Button(top, text='Move up',
                                   command=partial(move_button, 0))
        down_button = tkinter.Button(top, text='Move down',
                                     command=partial(move_button, 1))
        right_button = tkinter.Button(top, text='Move right',
                                      command=partial(move_button, 2))
        left_button = tkinter.Button(top, text='Move left',
                                     command=partial(move_button, 3))
        start_recording_button = tkinter.Button(top, text='Start recording',
                                             command=start_recording)
        stop_recording_button = tkinter.Button(top, text='Stop recording',
                                            command=stop_recording)
        self.home_z_button = tkinter.Button(top, text='Toggle home z',
                                            command=home_z_command)
        toggle_bright_particle_button = tkinter.Button(
            top, text='Toggle particle brightness',
            command=toggle_bright_particle)

        threshold_entry = tkinter.Entry(top, bd=5)
        temperature_entry = tkinter.Entry(top, bd=5)
        exposure_entry = tkinter.Entry(top, bd=5)

        toggle_tracking_button = tkinter.Button(
            top, text='Toggle particle tracking', command=toggle_tracking)

        def set_threshold():
            entry = threshold_entry.get()
            try:
                threshold = int(entry)
                if 0 < threshold < 255:
                    c_p['particle_threshold'] = threshold
                    print("Threshold set to ", threshold)
                else:
                    print('Threshold out of bounds')
            except:
                print('Cannot convert entry to integer')
            threshold_entry.delete(0, last=5000)

        def set_temperature():
            entry = temperature_entry.get()
            try:
                temperature = float(entry)
                if 20 < temperature < 40:
                    c_p['setpoint_temperature'] = temperature
                    print("Temperature set to ", temperature)
                else:
                    print('Temperature out of bounds, it is no good to cook or \
                          freeze your samples')
            except:
                print('Cannot convert entry to integer')
            temperature_entry.delete(0, last=5000)

        def set_exposure():
            #if c_p['camera_model'] == 'basler':
            entry = exposure_entry.get()
            if c_p['camera_model'] == 'basler':
                try:
                    exposure_time = int(entry)
                    if 59 < exposure_time < 4e5: # If you need more than that you are
                        c_p['exposure_time'] = exposure_time
                        print("Exposure time set to ", exposure_time)
                        c_p['new_settings_camera'] = True
                    else:
                        print('Exposure time out of bounds!')
                except:
                    print('Cannot convert entry to integer')
                exposure_entry.delete(0, last=5000)
            elif c_p['camera_model'] == 'ThorlabsCam':
                try:
                    exposure_time = float(entry)
                    if 0.01 < exposure_time < 100: # If you need more than that you are
                        c_p['exposure_time'] = exposure_time
                        print("Exposure time set to ", exposure_time)
                        c_p['new_settings_camera'] = True
                    else:
                        print('Exposure time out of bounds!')
                except:
                    print('Cannot convert entry to integer')
                exposure_entry.delete(0, last=5000)

        def connect_disconnect_motorX():
            c_p['connect_motor'][0] = not c_p['connect_motor'][0]

        def connect_disconnect_motorY():
            c_p['connect_motor'][1] = not c_p['connect_motor'][1]

        def connect_disconnect_piezo():
            c_p['connect_motor'][2] = not c_p['connect_motor'][2]

        threshold_button = tkinter.Button(
            top, text='Set threshold', command=set_threshold)
        focus_up_button = tkinter.Button(
            top, text='Move focus up', command=focus_up)
        focus_down_button = tkinter.Button(
            top, text='Move focus down', command=focus_down)
        temperature_button = tkinter.Button(
            top, text='Set setpoint temperature', command=set_temperature)
        zoom_in_button = tkinter.Button(top, text='Zoom in', command=zoom_in)
        zoom_out_button = tkinter.Button(top, text='Zoom out', command=zoom_out)
        temperature_output_button = tkinter.Button(top,
            text='toggle temperature output', command=toggle_temperature_output)
        set_exposure_button = tkinter.Button(top, text='Set exposure', command=set_exposure)
        experiment_schedule_button = tkinter.Button(top,
            text='Select experiment schedule',
            command=self.read_experiment_dictionary
            )
        # Motor buttons. Attributes of UserInterface class os we can easily change
        # the description text of them.
        self.toggle_motorX_button = tkinter.Button(
            top, text='Connect motor x', command=connect_disconnect_motorX)
        self.toggle_motorY_button = tkinter.Button(
            top, text='Connect motor y', command=connect_disconnect_motorY)
        self.toggle_piezo_button = tkinter.Button(
            top, text='Connect piezo motor', command=connect_disconnect_piezo)

        x_position = 1220
        x_position_2 = 1420
        y_position = get_y_separation()
        y_position_2 = get_y_separation()

        # Place all the buttons, starting with first column
        up_button.place(x=x_position, y=y_position.__next__())
        down_button.place(x=x_position, y=y_position.__next__())
        right_button.place(x=x_position, y=y_position.__next__())
        left_button.place(x=x_position, y=y_position.__next__())
        start_recording_button.place(x=x_position, y=y_position.__next__())
        stop_recording_button.place(x=x_position, y=y_position.__next__())
        toggle_bright_particle_button.place(x=x_position, y=y_position.__next__())
        threshold_entry.place(x=x_position, y=y_position.__next__())
        threshold_button.place(x=x_position, y=y_position.__next__())
        toggle_tracking_button.place(x=x_position, y=y_position.__next__())
        focus_up_button.place(x=x_position, y=y_position.__next__())
        focus_down_button.place(x=x_position, y=y_position.__next__())
        temperature_entry.place(x=x_position, y=y_position.__next__())
        temperature_button.place(x=x_position, y=y_position.__next__())
        zoom_in_button.place(x=x_position, y=y_position.__next__())
        zoom_out_button.place(x=x_position, y=y_position.__next__())

        # Second column
        #temperature_output_button.place(x=x_position_2, y=y_position_2.__next__())
        exposure_entry.place(x=x_position_2, y=y_position_2.__next__())
        set_exposure_button.place(x=x_position_2, y=y_position_2.__next__())
        experiment_schedule_button.place(x=x_position_2, y=y_position_2.__next__())
        self.toggle_motorX_button.place(x=x_position_2, y=y_position_2.__next__())
        self.toggle_motorY_button.place(x=x_position_2, y=y_position_2.__next__())
        self.toggle_piezo_button.place(x=x_position_2, y=y_position_2.__next__())
        self.home_z_button.place(x=x_position_2, y=y_position_2.__next__())

    def create_SLM_window(self, _class):
        try:
            if self.new.state() == "normal":
                self.new.focus()
        except:
            self.new = tkinter.Toplevel(self.window)
            self.SLM_Window = _class(self.new)

    def get_temperature_info(self):
        global c_p
        if c_p['temperature_controller_connected']:
            temperature_info = 'Current objective temperature is: '+str(c_p['current_temperature'])+' C'+'\n setpoint temperature is: '+str(c_p['setpoint_temperature'])+' C'
            if c_p['temperature_stable']:
                temperature_info += '\nTemperature is stable. '
            else:
                temperature_info += '\nTemperature is not stable. '
            if c_p['temperature_output_on']:
                temperature_info += '\n Temperature controller output is on.'
            else:
                temperature_info += '\n Temperature controller output is off.'
        else:
            temperature_info = 'Temperature controller is not connected.'


        return temperature_info

    def get_position_info(self):

        global c_p
        # Add position info
        position_text = 'x: '+str(c_p['motor_current_pos'][0])+\
            'mm   y: '+str(c_p['motor_current_pos'][1])+\
            'mm   z: '+str(c_p['motor_current_pos'][2])
        position_text += '\n Experiments run ' + str(c_p['experiment_progress'])
        position_text += ' out of ' + str(c_p['nbr_experiments'])
        position_text += '  ' + str(c_p['experiment_runtime']) + 's run out of ' + str(c_p['recording_duration'])
        position_text += '\n Current search direction is: ' + str(c_p['search_direction'] + '\n')

        # Add motor connection info
        x_connected = 'connected. ' if c_p['motors_connected'][0] else 'disconnected.'
        y_connected = 'connected. ' if c_p['motors_connected'][1] else 'disconnected.'
        piezo_connected = 'connected. ' if c_p['motors_connected'][2] else 'disconnected.'

        position_text += 'Motor-X is ' + x_connected
        position_text += ' Motor-Y is ' + y_connected + '\n'
        position_text += ' Focus (piezo) motor is ' + piezo_connected + '\n'

        return position_text

    def update_motor_buttons(self):
        # Motor connection buttons
        x_connect = 'Disconnect' if c_p['connect_motor'][0] else 'Connect'
        self.toggle_motorX_button.config(text=x_connect + ' motor x')
        y_connect = 'Disconnect' if c_p['connect_motor'][1] else 'Connect'
        self.toggle_motorY_button.config(text=y_connect + ' motor y')
        piezo_connected = 'Disconnect' if c_p['connect_motor'][2] else 'Connect'
        self.toggle_piezo_button.config(text=piezo_connected + ' piezo motor')

    def update_home_button(self):
        if c_p['return_z_home']:
            self.home_z_button.config(text='Z is homing. Press to stop')
        else:
            self.home_z_button.config(text='Press to home z')

    def create_indicators(self):
        global c_p
        # Update if recording is turned on or not
        if c_p['recording']:
            self.recording_label = Label(
                self.window, text='recording is on', bg='green')
        else:
            self.recording_label = Label(
                self.window, text='recording is off', bg='red')
        self.recording_label.place(x=1220, y=750)

        if c_p['tracking_on']:
             self.tracking_label = Label(
                 self.window, text='particle tracking is on', bg='green')
        else:
            self.tracking_label = Label(
                self.window, text='particle tracking is off', bg='red')
        self.tracking_label.place(x=1220, y=780)

        self.position_label = Label(self.window, text=self.get_position_info())
        self.position_label.place(x=1420, y=400)
        self.temperature_label = Label(self.window, text=self.get_temperature_info())
        self.temperature_label.place(x=1420, y=540)

    def update_indicators(self):
        '''
        Helper function for updating on-screen indicators
        '''
        global c_p
        # Update if recording is turned on or not
        if c_p['recording']:
            self.recording_label.config(text='recording is on', bg='green')
        else:
            self.recording_label.config(text='recording is off', bg='red')

        if c_p['tracking_on']:
            self.tracking_label.config(text='particle tracking is on',bg='green')
        else:
            self.tracking_label.config(text='particle tracking is off', bg='red')

        self.temperature_label.config(text=self.get_temperature_info())

        self.position_label.config(text=self.get_position_info())

        self.update_motor_buttons()
        self.update_home_button()

    def resize_display_image(self, img):
        img_size = np.shape(img)
        if img_size[1]==self.canvas_width or img_size[0] == self.canvas_height:
            return img

        if img_size[1]/self.canvas_width > img_size[0]/self.canvas_height:
            dim = (int(self.canvas_width/img_size[1]*img_size[0]), int(self.canvas_width))
        else:
            dim = ( int(self.canvas_height), int(self.canvas_height/img_size[0]*img_size[1]))
        return cv2.resize(img, (dim[1],dim[0]), interpolation = cv2.INTER_AREA)

    def update(self):
         # Get a frame from the video source
         #global image
         image = np.asarray(c_p['image'])
         image = image.astype('uint8')
         if c_p['phasemask_updated']:
              print('New phasemask')
              self.SLM_Window.update()
              c_p['phasemask_updated'] = False
         self.update_indicators()
         # TODO make it possible to overlay the positions of the trapped particles and the
         # estimated positions of the target positions
         #print(np.shape(image))
         self.photo = PIL.ImageTk.PhotoImage(image = PIL.Image.fromarray(self.resize_display_image(image)))
         self.canvas.create_image(0, 0, image = self.photo, anchor = tkinter.NW) # need to use a compatible image type

         # Update mini-window
         self.create_trap_image()
         self.mini_photo = PIL.ImageTk.PhotoImage(image = PIL.Image.fromarray(self.mini_image, mode='RGB'))
         self.mini_canvas.create_image(0, 0, image = self.mini_photo, anchor = tkinter.NW) # need to use a compatible image type

         self.window.after(self.delay, self.update)


class SLM_window(Frame):
    global c_p

    def __init__(self,c_p, master=None):
        Frame.__init__(self, master)
        self.master = master
        self.master.geometry("1920x1080+1920+0")
        self.pack(fill=BOTH, expand=1)

        render = PIL.ImageTk.PhotoImage(image=PIL.Image.fromarray(c_p['phasemask']))
        self.img = Label(self, image=render)
        self.img.place(x=420, y=0)
        self.img.image = image
        self.delay = 500 # Delay in ms
        self.c_p = c_p
        self.update()

    def update(self):
        # This implementation does work but is perhaps a tiny bit janky
        self.photo = PIL.ImageTk.PhotoImage(image=PIL.Image.fromarray(self.c_p['phasemask']))
        del self.img.image
        self.img = Label(self, image=self.photo)
        self.img.image = self.photo # This ate lots of memory
        self.img.place(x=420, y=0) # Do not think this is needed


def compensate_focus():
    '''
    Function for compensating the change in focus caused by x-y movement.
    Returns the positon in ticks which z  should take to compensate for the focus
    '''
    global c_p
    new_z_pos = (c_p['z_starting_position']
        +c_p['z_x_diff']*(c_p['motor_starting_pos'][0] - c_p['motor_current_pos'][0])
        +c_p['z_y_diff']*(c_p['motor_starting_pos'][1] - c_p['motor_current_pos'][1]) )
    new_z_pos += c_p['temperature_z_diff']*(c_p['current_temperature']-c_p['starting_temperature'])
    return int(new_z_pos)


class ExperimentControlThread(threading.Thread):
   '''
   Thread which does the tracking.
   '''
   def __init__(self, threadID, name):
        threading.Thread.__init__(self)
        self.threadID = threadID
        self.name = name
        self.setDaemon(True)

   def __del__(self):
       c_p['tracking_on'] = False

   def catch_particle(self, min_index_trap=None, min_index_particle=None):
        '''
        Function for determimning where and how to move when min_index_particle
        has been found
        '''
        global c_p
        if min_index_particle is not None:
          c_p['target_trap_pos'] = [c_p['traps_relative_pos'][0][min_index_trap],
                                    c_p['traps_relative_pos'][1][min_index_trap]]
          c_p['target_particle_center'] = [c_p['particle_centers'][0][min_index_particle],
                                            c_p['particle_centers'][1][min_index_particle]]

          if True in c_p['traps_occupied']:
              c_p['xy_movement_limit'] = 40
              # Some traps are occupied. Want to avoid catching more than one
              # particle per trap.
              filled_traps_locs = []
              for idx, occupied in enumerate(c_p['traps_occupied']):
                  if occupied:
                      filled_traps_locs.append([c_p['traps_relative_pos'][0][idx],
                      c_p['traps_relative_pos'][1][idx] ])
              x, y, success = path_search(filled_traps_locs,
                              target_particle_location=c_p['target_particle_center'],
                              target_trap_location=c_p['target_trap_pos'])
          else:
              success = False
              c_p['xy_movement_limit'] = 1200
          if success:
              c_p['motor_movements'][0] = -x
              c_p['motor_movements'][1] = y
          else:
              c_p['motor_movements'][0] = -(c_p['target_trap_pos'][0] - c_p['target_particle_center'][0]) # Note: Sign of this depends on setup
              c_p['motor_movements'][1] = c_p['target_trap_pos'][1] - c_p['target_particle_center'][1]

        else:
            c_p['target_particle_center'] = []

   def lift_for_experiment(self,patiance=3):
       '''
       Assumes that all particles have been caught.
       patiance, how long(s) we allow a trap to be unoccipied for

       Returns true if lift succeded
       '''
       z_starting_pos = compensate_focus()
       patiance_counter = 0
       print('Lifting time. Starting from ', z_starting_pos, ' lifting ',
            c_p['target_experiment_z'])
       while c_p['target_experiment_z'] > c_p['motor_current_pos'][2] - z_starting_pos:
            time.sleep(0.2)
            all_filled, nbr_particles, min_index_trap, min_index_particle  =\
                self.check_exp_conditions()
            if all_filled:
                c_p['z_movement'] = 40
                c_p['return_z_home'] = False
                patiance_counter = 0
            else:
                patiance_counter += 1
            if patiance_counter >= patiance or not c_p['tracking_on']:
                c_p['return_z_home'] = True
                c_p['z_movement'] = 0
                return False
       print('Lifting done. Now at',  c_p['motor_current_pos'][2])
       return True

   def check_exp_conditions(self, tracking_func=None):
        '''
        Checks if all traps are occupied. Returns true if this is the case.
        Tries to catch the closes unoccupied particle.
        '''
        if tracking_func is None:
            x, y = fpt.find_particle_centers(copy.copy(image),
                      threshold=c_p['particle_threshold'],
                      particle_size_threshold=c_p['particle_size_threshold'],
                      bright_particle=c_p['bright_particle'])
        else:
            x, y = tracking_func(copy.copy(image))

        c_p['particle_centers'] = [x, y]
        c_p['traps_occupied'] = [False for i in range(len(c_p['traps_absolute_pos'][0]))]
        min_index_trap, min_index_particle = find_closest_unoccupied()

        if False not in c_p['traps_occupied']:
            # All traps have been occupied
            return True, -1, min_index_trap, min_index_particle
        # Not all traps have been occupied, might need to go searching
        return False, len(x), min_index_trap, min_index_particle

   def run_experiment(self, duration):
        '''
        Run an experiment for 'duration'.
        Returns 0 if it ran to the end without interruption otherwise it
        returns the amount of time remaining of the experiment.
        '''
        start = time.time()
        now = datetime.now()
        time_stamp = str(now.hour) + '-' + str(now.minute)

        # Taking snapshot before zooming in so user can see if there are
        # particles in the background which may interfere with measurement.

        snapshot(c_p['measurement_name']+'_pre'+time_stamp)
        zoom_in()
        c_p['recording'] = True
        patiance = 50
        patiance_counter = 0
        while time.time() <= start + duration and c_p['tracking_on']:
            all_filled, nbr_particles, min_index_trap, min_index_particle  =\
                self.check_exp_conditions()
            if all_filled:
                patiance_counter = 0
                time.sleep(1)
                c_p['experiment_runtime'] = np.round(time.time() - start)
            else:
                patiance_counter += 1
            if patiance_counter > patiance:
                break
        c_p['recording'] = False
        zoom_out()
        snapshot(c_p['measurement_name']+'_after'+time_stamp)
        if time.time() >= start + duration:
            return 0
        return start + duration - time.time()

   def add_ghost_traps(self, ghost_traps_x, ghost_traps_y, ghost_traps_z=None):
       '''
       Function for adding ghost traps after having lifted the particles.
       '''
       # Update number of ghost traps.
       c_p['nbr_ghost_traps'] = len(ghost_traps_x)

       # Convert traps positions to SLM positions.
       if min(ghost_traps_x) >= 1:
           ghost_traps_x = pixels_to_SLM_locs(ghost_traps_x, 0)
       if min(ghost_traps_y) >= 1:
           ghost_traps_y = pixels_to_SLM_locs(ghost_traps_y, 1)
       if ghost_traps_z is None:
           ghost_traps_z = np.zeros(c_p['nbr_ghost_traps'])

       # Append ghost traps to xm, ym and zm
       c_p['xm'] += ghost_traps_x
       c_p['ym'] += ghost_traps_y
       c_p['zm'] += ghost_traps_z

       # Update the phasemask
       c_p['new_phasemask'] = True
       while c_p['new_phasemask'] and c_p['tracking_on']:
           time.sleep(0.1)

   def run(self):
        '''
        Plan - have an experiment procedure.
        Before each experiment is allowed to start make sure all traps
        which are supposed to be filled are filled.
        Then lift the particles and start recording. If any particle
        is dropped go down and refill the traps and continue* the
        experiment.
        In between each experiment(when experiment parameters are to be changed)
        try to move the particles which are already trapped rather than
        cathing new ones (unless this is necessary). Then change all desired parameters.

        Control the experiments with a experiment Dictionary which
        keeps track of 'c_p' which are to be changed during the experiment.
        For instance might desire to change LGO orders as well as
        particle distance and temperature,then this should be possible

        * Do not record the full length but only the missing part of the video
        '''

        # TODO make the program understand when two particles have been trapped
        # in the same trap. - Possible solution: Train an AI to detect this.
        global image
        global c_p
        c_p['nbr_experiments'] = len(c_p['experiment_schedule'])
        c_p['experiment_progress'] = 0

        while c_p['program_running']: # Change to continue tracking?
            time.sleep(0.3)
            # Look through the whole schedule, a list of dictionaries.

            if c_p['tracking_on'] and c_p['experiment_progress'] < c_p['nbr_experiments']:
                setup_dict = c_p['experiment_schedule'][c_p['experiment_progress']]
                print('Next experiment is', setup_dict)
                run_finished = False
                update_c_p(setup_dict)
                full_xm = copy.copy(c_p['xm']) # for adding one trap at a time.
                full_ym = copy.copy(c_p['ym']) # Using copy since
                time_remaining = c_p['recording_duration']
                all_filled, nbr_particles, min_index_trap, min_index_particle = self.check_exp_conditions()

                # Check if we need to go down and look for more particles in
                # between the experiments
                if all_filled:
                    nbr_active_traps = len(full_xm)
                else:
                    # Not all traps were filled, need to home and activate
                    # only the first trap
                    c_p['return_z_home'] = True
                    time.sleep(1)
                    if c_p['activate_traps_one_by_one']:
                        nbr_active_traps = min(3,len(full_xm))
                        active_traps_dict = {'xm':full_xm[:nbr_active_traps],
                            'ym':full_ym[:nbr_active_traps]}
                        update_c_p(active_traps_dict)
                # Start looking for particles.
                while not run_finished and c_p['tracking_on']:
                   time.sleep(0.3)
                   # We are (probably) in full frame mode looking for a particle

                   all_filled, nbr_particles, min_index_trap, min_index_particle = self.check_exp_conditions()

                   if not all_filled and nbr_particles <= c_p['traps_occupied'].count(True):
                       # Fewer particles than traps. Look for more particles.
                       c_p['return_z_home'] = True
                       search_for_particles()

                   elif not all_filled and nbr_particles > c_p['traps_occupied'].count(True):
                       # Untrapped particles and unfilled traps. Catch particles
                       self.catch_particle(min_index_trap=min_index_trap,
                            min_index_particle=min_index_particle)

                   elif all_filled:

                       # All active traps are filled, activate a new one if
                       # there are more to activate
                       if len(c_p['xm']) < len(full_xm):
                            nbr_active_traps += 1
                            active_traps_dict = {'xm':full_xm[:nbr_active_traps],
                                'ym':full_ym[:nbr_active_traps]}
                            update_c_p(active_traps_dict)

                       # No more traps to activate, can start lifting.
                       elif self.lift_for_experiment():
                           print('lifted!')

                           if 'ghost_traps_x' in setup_dict:
                               print('Adding ghost traps')
                               ghost_traps_z = None if 'ghost_traps_z' not in setup_dict else setup_dict['ghost_traps_z']
                               self.add_ghost_traps(setup_dict['ghost_traps_x'],
                                                    setup_dict['ghost_traps_y'],
                                                    ghost_traps_z)
                               # Will currently add ... which will
                           # Particles lifted, can start experiment.
                           time_remaining = self.run_experiment(time_remaining)
                       else:
                           c_p['return_z_home'] = True

                   if time_remaining < 1:
                       run_finished = True
                       c_p['experiment_progress'] += 1

        c_p['return_z_home'] = True
        print('I AM DONE NOW QUITTING!')


def get_adjacency_matrix(nx, ny):
    '''
    Function for calculating the adjacency matrix used in graph theory to
    describe which nodes are neighbours.
    '''
    X, Y = np.meshgrid(
        np.arange(0, nx),
        np.arange(0, ny)
    )

    nbr_nodes = nx*ny
    XF = np.reshape(X, (nbr_nodes, 1))
    YF = np.reshape(Y, (nbr_nodes, 1))
    adjacency_matrix = np.zeros((nbr_nodes, nbr_nodes))
    for idx in range(nx*ny):
        distance_map = (X - XF[idx])**2 + (Y - YF[idx])**2
        adjacency_matrix[idx, :] = np.reshape(distance_map, (nbr_nodes)) <= 3
        adjacency_matrix[idx, idx] = 0
    return adjacency_matrix


def path_search(filled_traps_locs, target_particle_location,
                target_trap_location):
    '''
    Function for finding paths to move the stage so as to trap more particles
    without accidentally trapping extra particles.
    Divides the AOI into a grid and calculates the shortest path to the trap
    without passing any already occupied traps.

    Parameters
    ----------
    filled_traps_locs : TYPE list of list of
        traps locations [[x1, y1], [x2, y2]...]
        DESCRIPTION.
    target_particle_location : TYPE list [x,y] of target particle location [px]
        DESCRIPTION.
    target_trap_location : TYPE list of target trap location [px]
        DESCRIPTION.

    Returns
    -------
    TYPE move_x, move_y, success
        DESCRIPTION. The move to make to try and trap the particle without it
        getting caught in another trap along the way
        success - True if path was not blocked by other particles and a move
        was found. False otherwise.

    '''
    # TODO Make it possible to try and
    # move in between particles.
    global c_p

    nx = int( (c_p['AOI'][1]-c_p['AOI'][0]) / c_p['cell_width'])
    ny = int( (c_p['AOI'][3]-c_p['AOI'][2]) / c_p['cell_width'])
    X, Y = np.meshgrid(
        np.arange(0, nx),
        np.arange(0, ny)
    )


    nbr_nodes = nx*ny
    node_weights = 1e6 * np.ones((nbr_nodes, 1))  # Initial large weights
    unvisited_set = np.zeros(nbr_nodes)  # Replace with previous nodes
    previous_nodes = -1 * np.ones(nbr_nodes)

    def matrix_to_array_index(x, y, nx):
        return x + y * nx

    def array_to_matrix_index(idx, nx):
        y = idx // nx
        x = np.mod(idx, nx)
        return x, y

    def loc_to_index(x, y, nx):
        x = int(x/c_p['cell_width'])
        y = int(y/c_p['cell_width'])
        return matrix_to_array_index(x, y, nx)

    adjacency_matrix = get_adjacency_matrix(nx, ny)

    trap_radii = 3
    for location in filled_traps_locs:
        x = location[0] / c_p['cell_width']
        y = location[1] / c_p['cell_width']
        distance_map = (X - x)**2 + (Y - y)**2
        indices = [i for i, e in enumerate(np.reshape(distance_map, (nbr_nodes))) if e < trap_radii]
        adjacency_matrix[:, indices] = 0
        node_weights[indices] = 50
        node_weights[matrix_to_array_index(int(x), int(y), nx)] = 40
        unvisited_set[matrix_to_array_index(int(x), int(y), nx)] = 1

    target_node = loc_to_index(target_trap_location[0],
                               target_trap_location[1], nx)
    current_node = loc_to_index(target_particle_location[0],
                                target_particle_location[1], nx)

    # Djikstra:
    node_weights[current_node] = 0
    unvisited_set[current_node] = 1
    previous_nodes[current_node] = 0

    def update_dist(current_node, adjacency_indices, node_weights,
                    previous_nodes):
        for index in adjacency_indices:
            if node_weights[current_node] + 1 < node_weights[index]:
                node_weights[index] = node_weights[current_node] + 1
                # All distances are either inf or 1
                previous_nodes[index] = current_node

    def find_next_node(unvisited_set, node_weights):
        res_list = [i for i, value in enumerate(unvisited_set) if value == 0]
        min_value = 1e6
        min_idx = -1
        for index in res_list:
            if node_weights[index] < min_value:
                min_idx = index
                min_value = node_weights[index]
        return min_idx

    iterations = 0
    while unvisited_set[target_node] == 0 and iterations <= nbr_nodes:
        adjacency_indices = [i for i, e in enumerate(adjacency_matrix[current_node,:]) if e == 1]
        update_dist(current_node, adjacency_indices,
                    node_weights, previous_nodes)
        current_node = find_next_node(unvisited_set, node_weights)
        unvisited_set[current_node] = 1
        iterations += 1

    previous = target_node
    node_weights[previous]
    prev_x = []
    prev_y = []

    while previous != 0:
        node_weights[previous] = -3
        tmp_x, tmp_y = array_to_matrix_index(previous, nx)
        prev_x.append(tmp_x)
        prev_y.append(tmp_y)
        previous = int(previous_nodes[previous])
        if previous == -1:
            break

    if previous == -1:
        return 0, 0, False
    elif len(prev_x) > 3:
        x_move = prev_x[-3] * c_p['cell_width'] - target_particle_location[0]
        # SHould be -2 but was very slow
        y_move = prev_y[-3] * c_p['cell_width'] - target_particle_location[1]
        return x_move, y_move, True
    else:
        try:
            x_move = prev_x[-2] * c_p['cell_width'] - target_particle_location[0]
            y_move = prev_y[-2] * c_p['cell_width'] - target_particle_location[1]
            return x_move, y_move, True
        except:
            return 0, 0, False


def update_c_p(update_dict, wait_for_completion=True):
    '''
    Simple function for updating c_p['keys'] with new values 'values'.
    Ensures that all updates where successfull.
    Parameter wait_for_completion should be set to True if there is a need
    to wait for phasemask to be finished updating before continuing the program.

    Highly suggest usage of measurement_name to make it easier to keep track of
    the data.
    '''

    global c_p

    ok_parameters = ['use_LGO', 'LGO_order', 'xm', 'ym', 'zm', 'setpoint_temperature',
    'recording_duration', 'target_experiment_z', 'SLM_iterations',
    'temperature_output_on','activate_traps_one_by_one','need_T_stable',
    'measurement_name','phasemask']

    requires_new_phasemask = ['use_LGO', 'LGO_order', 'xm', 'ym', 'zm', 'SLM_iterations']

    for key in update_dict:
        if key in ok_parameters:
            try:
                if key == 'xm' and min(update_dict[key]) > 1:
                    c_p[key] = pixels_to_SLM_locs(update_dict[key], 0)
                    print('xm ' ,update_dict[key])
                elif key == 'ym' and min(update_dict[key]) > 1:
                    c_p[key] = pixels_to_SLM_locs(update_dict[key], 1)
                    print('ym ',update_dict[key])
                else:
                    c_p[key] = update_dict[key]

            except:
                print('Could not update control parameter ', key, 'with value',
                value)
                return
        else:
            print('Invalid key: ', key)

    # Need to update measurement_name even if it is not in measurement to
    # prevent confusion

    if 'ghost_traps_x' or 'ghost_traps_y' not in update_dict:
        c_p['nbr_ghost_traps'] = 0

    # Check that both xm and ym are updated
    if len(c_p['xm']) > len(c_p['ym']):
        c_p['xm'] = c_p['xm'][:len(c_p['ym'])]
        print(' WARNING! xm and ym not the same length, cutting off xm!')
    if len(c_p['ym']) > len(c_p['xm']):
        c_p['ym'] = c_p['ym'][:len(c_p['xm'])]
        print(' WARNING! xm and ym not the same length, cutting off ym!')

    # update phasemask. If there was an old one linked use it.
    if 'phasemask' not in update_dict:
        for key in update_dict:
            if key in requires_new_phasemask:
                c_p['new_phasemask'] = True
    else:
        # Manually change phasemask without SLM thread
        c_p['phasemask_updated'] = True
        SLM_loc_to_trap_loc(c_p['xm'], c_p['ym'])

    # Wait for new phasemask if user whishes this
    while c_p['new_phasemask'] and wait_for_completion:
        time.sleep(0.3)

    # Check if there is an old phasemask to be used.
    # if 'load_phasemask' in update_dict:
    #     try:
    #         data = np.load(update_dict['load_phasemask'])
    #         c_p['phasemask'] = data['phasemask']
    #         time.sleep(0.5)
    #     except:
    #         print('Could not load phasemask from ', update_dict['load_phasemask'])

    # Await stable temperature
    while c_p['need_T_stable'] and not c_p['temperature_stable'] and\
        c_p['temperature_controller_connected']:
        time.sleep(0.3)


def count_interior_particles(margin=30):
    '''
    Function for counting the number of particles in the interior of the frame.
    margin
    '''
    global c_p
    interior_particles = 0
    for position in c_p['particle_centers']:
        interior_particles += 1

    return interior_particles


def find_focus():
    """
    Function which uses the laser to find a focus point
    """

    # Idea - Search for a focus, first down 1000-ticks then up 2000 ticks from down pos
    # Take small steps :10-20 per step. Between each step check if intensity
    # Around the traps have increased enough
    #Direction focus down
    #
    focus_found = False
    while not focus_found:


        print('a')


def in_focus(margin=40):
    '''
    Function for determining if a image is in focus by looking at the intensity
    close to the trap positions and comparing it to the image median.
    # Highly recommended to change to only one trap before using this function
    # This function is also very unreliable. Better to use the old method +
    # deep learning I believe.
    '''

    global image
    global c_p
    median_intesity = np.median(image)


    if c_p['camera_model'] == 'basler':
        image_limits = [672,512]
    else:
        image_limits = [1200,1000]

    left = int(max(min(c_p['traps_absolute_pos'][0]) - margin, 0))
    right = int(min(max(c_p['traps_absolute_pos'][0]) + margin, image_limits[0]))
    up = int(max(min(c_p['traps_absolute_pos'][1]) - margin, 0))
    down = int(min(max(c_p['traps_absolute_pos'][1]) + margin, image_limits[1]))

    expected_median = (left - right) * (up - down) * median_intesity
    actual_median = np.sum(image[left:right,up:down])

    print(median_intesity,actual_median)
    print( expected_median + c_p['focus_threshold'])
    if actual_median > (expected_median + c_p['focus_threshold']):
        return True
    return False


def predict_particle_position_network(network,half_image_width=50,
    network_image_width=101,
    print_position=False):
    '''
    Function for making g a prediciton with a network and automatically updating the center position array.
    inputs :
        network - the network to predict with. Trained with deeptrack
        half_image_width - half the width of the image. needed to convert from deeptrack output to pixels
        network_image_width - Image width that the newtwork expects
        print_position - If the predicted positon should be printed in the console or not
    Outputs :
        Updates the center position of the particle
    '''
    global image
    global c_p
    resized = cv2.resize(copy.copy(image), (network_image_width,network_image_width), interpolation = cv2.INTER_AREA)
    pred = network.predict(np.reshape(resized/255,[1,network_image_width,network_image_width,1]))

    c_p['target_particle_center'][0] = half_image_width + pred[0][1] * half_image_width
    c_p['target_particle_center'][1] = half_image_width + pred[0][0] * half_image_width

    if print_position:
        print('Predicted posiiton is ',c_p['particle_centers'])


def get_particle_trap_distances():
    '''
    Calcualtes the distance between all particles and traps and returns a
    distance matrix, ordered as distances(traps,particles),
    To clarify the distance between trap n and particle m is distances[n][m].
    '''
    global c_p
    update_traps_relative_pos() # just in case
    nbr_traps = len(c_p['traps_relative_pos'][0])
    nbr_particles = len(c_p['particle_centers'][0])
    distances = np.ones((nbr_traps, nbr_particles))

    for i in range(nbr_traps):
        for j in range(nbr_particles):
            dx = (c_p['traps_relative_pos'][0][i] - c_p['particle_centers'][0][j])
            dy = (c_p['traps_relative_pos'][1][i] - c_p['particle_centers'][1][j])
            distances[i,j] = np.sqrt(dx * dx + dy * dy)
    return distances


def trap_occupied(distances, trap_index):
    '''
    Checks if a specific trap is occupied by a particle. If so set that trap to occupied.
    Updates if the trap is occupied or not and returns the index of the particle in the trap
    '''
    global c_p

    # Check that trap index is ok
    if trap_index > len(c_p['traps_occupied']) or trap_index < 0:
        print('Trap index out of range')
        return None
    for i in range(len(distances[trap_index, :])):
        dist_to_trap = distances[trap_index, i]
        if dist_to_trap <= c_p['movement_threshold']:
            c_p['traps_occupied'][trap_index] = True
            return i
    try:
        c_p['traps_occupied'][trap_index] = False
        return None
    except:
        print(" Indexing error for trap index", str(trap_index),\
        " length is ",len(c_p['traps_occupied']))
        return None


def check_all_traps(distances=None):
    '''
    Updates all traps to see if they are occupied.
    Returns the indices of the particles which are trapped. Indices refers to their
    position in the c_p['particle_centers'] array.
    Returns an empty array if there are no trapped particles.

    '''

    if distances is None:
        distances = get_particle_trap_distances()
    trapped_particle_indices = []
    nbr_traps = len(distances)
    for trap_index in range(nbr_traps):
        # Check for ghost traps
        if trap_index >= nbr_traps - c_p['nbr_ghost_traps']:
            c_p['traps_occupied'][trap_index] = True
        else:
            # Check occupation of non ghost traps.
            trapped_particle_index = trap_occupied(distances, trap_index)
            if trapped_particle_index is not None:
                trapped_particle_indices.append(trapped_particle_index)
    return trapped_particle_indices


def find_closest_unoccupied():
    '''
    Function for finding the paricle and (unoccupied) trap which are the closest
    Returns : min_index_trap,min_index_particle.
        Index of the untrapped particle closest to an unoccupied trap.
    '''

    distances = get_particle_trap_distances()
    trapped_particles = check_all_traps(distances)
    distances[:,trapped_particles] = 1e6 # These indices are not ok, put them very large

    min_distance = 2000 # If the particle is not within 2000 pixels then it is not within the frame
    min_index_particle = None # Index of particle which is closes to an unoccupied trap
    min_index_trap = None # Index of unoccupied trap which is closest to a particle

    # Check all the traps
    for trap_idx in range(len(c_p['traps_occupied'])):
        trapped = c_p['traps_occupied'][trap_idx]

        # If there is not a particle trapped in the trap check for the closest particle
        if not trapped and len(distances[0]) > 0:
            # Had problems with distances being [] if there were no particles
            particle_idx = np.argmin(distances[trap_idx])

            # If particle is within the threshold then update min_index and trap index as well as min distance
            if distances[trap_idx,particle_idx]<min_distance:
                min_distance = distances[trap_idx,particle_idx]
                min_index_trap = trap_idx
                min_index_particle = particle_idx

    return min_index_trap, min_index_particle


def move_button(move_direction):
    '''
    Button function for manually moving the motors a bit
    The direction refers to the direction a particle in the fiel of view will move on the screen
    move_direction = 0 => move up
    move_direction = 1 => move down
    move_direction = 2 => move right
    move_direction = 3 => move left
    '''
    global c_p
    move_distance = 200
    if move_direction==0:
        # Move up (Particles in image move up on the screen)
        c_p['motor_movements'][1] = move_distance
    elif move_direction==1:
        # Move down
        c_p['motor_movements'][1] = -move_distance
    elif move_direction==2:
        # Move right
        c_p['motor_movements'][0] = move_distance
    elif move_direction==3:
        # Move left
        c_p['motor_movements'][0] = -move_distance
    else:
        print('Invalid move direction')


def start_recording():
    '''
    Button function for starting of recording
    '''
    c_p['recording']= True
    print('Recording is on')


def stop_recording():
    '''
    Button function for starting of recording
    '''
    c_p['recording']= False
    print('Recording is off')


def snapshot(label=None):
    """
    Saves the latest frame captured by the camera into a jpg image.
    Will label it with date and time if no label is provided. Image is
    put into same folder as videos recorded.
    """
    global image
    global c_p
    if label == None:
        image_name = c_p['recording_path'] + "/frame-" +\
                    time.strftime("%d-%m-%Y-%H-%M-%S") +\
                    ".jpg"
    else:
        image_name = c_p['recording_path'] + '/' + label + '.jpg'
    cv2.imwrite(image_name, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    print('Took a snapshot of the experiment.')


def toggle_temperature_output():
    '''
    Function for toggling temperature output on/off.
    '''
    c_p['temperature_output_on'] = not c_p['temperature_output_on']
    print("c_p['temperature_output_on'] set to",c_p['temperature_output_on'])


def toggle_bright_particle():
    '''
    Function for switching between bright and other particle
    '''
    c_p['bright_particle'] = not c_p['bright_particle']
    print("c_p['bright_particle'] set to",c_p['bright_particle'])


def toggle_tracking():
    c_p['tracking_on'] = not c_p['tracking_on']
    print("Tracking is ",c_p['tracking_on'])


def focus_up():
    '''
    Used for focus button to shift focus slightly up
    '''
    c_p['z_starting_position'] += 5


def focus_down():
    '''
    Used for focus button to shift focus slightly up
    '''
    c_p['z_starting_position'] -= 5


def zoom_in(margin=60, use_traps=False):
    # TODO make these compatible with the new structure of the code
    '''
    Helper function for zoom button and zoom function.
    Zooms in on an area around the traps
    '''
    if c_p['camera_model'] == 'ThorlabsCam':
        left = max(min(c_p['traps_absolute_pos'][0]) - margin, 0)
        left = int(left // 20 * 20)
        right = min(max(c_p['traps_absolute_pos'][0]) + margin, 1200)
        right = int(right // 20 * 20)
        up = max(min(c_p['traps_absolute_pos'][1]) - margin, 0)
        up = int(up // 20 * 20)
        down = min(max(c_p['traps_absolute_pos'][1]) + margin, 1000)
        down = int(down // 20 * 20)
    else:
        left = max(min(c_p['traps_absolute_pos'][0]) - margin, 0)
        left = int(left // 16 * 16)
        right = min(max(c_p['traps_absolute_pos'][0]) + margin, 672)
        right = int(right // 16 * 16)
        up = max(min(c_p['traps_absolute_pos'][1]) - margin, 0)
        up = int(up // 16 * 16)
        down = min(max(c_p['traps_absolute_pos'][1]) + margin, 512)
        down = int(down // 16 * 16)

    #c_p['framerate'] = 500
    # Note calculated framerate is automagically saved.
    CameraControls.set_AOI(c_p, left=left, right=right, up=up, down=down)


def zoom_out():
    if c_p['camera_model'] == 'ThorlabsCam':
        CameraControls.set_AOI(c_p, left=0, right=1200, up=0, down=1000)
        #c_p['framerate'] = 500
    else:
        CameraControls.set_AOI(c_p, left=0, right=672, up=0, down=512)


def search_for_particles():
    '''
    Function for searching after particles. Threats the sample as a grid and
    systmatically searches it
    '''
    x_max = 0.005 # [mm]
    delta_y = 3 # [mm]
    # Make movement
    if c_p['search_direction']== 'right':
        c_p['motor_movements'][0] = 300 # [px]

    elif c_p['search_direction']== 'left':
        c_p['motor_movements'][0] = -300

    elif c_p['search_direction']== 'up':
        c_p['motor_movements'][1] = 300

    elif c_p['search_direction']== 'down': # currently not used
        c_p['motor_movements'][1] = -300

    if c_p['search_direction']== 'up' and \
        (c_p['motor_current_pos'][1]-c_p['motor_starting_pos'][1])>delta_y:
        c_p['search_direction']= 'right'
        c_p['x_start'] = c_p['motor_current_pos'][0]
        print('changing search direction to right, x_start is ',c_p['x_start'] )

    if c_p['search_direction']== 'right' and \
        (c_p['motor_current_pos'][0]-c_p['x_start'])>x_max:

        if c_p['motor_current_pos'][1] - c_p['motor_starting_pos'][1]>delta_y/2:
            c_p['search_direction'] = 'down'
            print('changing search direction to down')
        else:
            c_p['search_direction'] = 'up'
            print('changing search direction to up')
    if c_p['search_direction']== 'down' \
        and (c_p['motor_current_pos'][1] - c_p['motor_starting_pos'][1])<0:
        c_p['search_direction']=='right'
        print('changing search direction to right')


def update_traps_relative_pos():
    global c_p
    tmp_x = [x - c_p['AOI'][0] for x in c_p['traps_absolute_pos'][0] ]
    tmp_y = [y - c_p['AOI'][2] for y in c_p['traps_absolute_pos'][1] ]
    tmp = np.asarray([tmp_x, tmp_y])
    c_p['traps_relative_pos'] = tmp


def pixels_to_SLM_locs(locs, axis):
    '''
    Function for converting from PIXELS to SLM locations.
    '''
    global c_p
    if axis != 0 and axis != 1:
        print('cannot perform conversion, incorrect choice of axis')
        return locs
    offset = c_p['slm_x_center'] if not axis else c_p['slm_y_center']
    new_locs = [((x - offset) / c_p['slm_to_pixel']) for x in locs]
    return new_locs


def SLM_loc_to_trap_loc(xm, ym):
    '''
    Fucntion for updating the traps position based on their locaitons
    on the SLM.
    '''
    global c_p
    tmp_x = [x * c_p['slm_to_pixel'] + c_p['slm_x_center'] for x in xm]
    tmp_y = [y * c_p['slm_to_pixel'] + c_p['slm_y_center'] for y in ym]
    tmp = np.asarray([tmp_x, tmp_y])
    c_p['traps_absolute_pos'] = tmp
    print('Traps are at: ', c_p['traps_absolute_pos'] )
    update_traps_relative_pos()


def save_phasemask():
    # Helperfunction for saving the SLM.
    # Should probably save parameters of this at same time as well.
    global c_p

    now = datetime.now()
    phasemask_name = c_p['recording_path'] + '/phasemask-'+\
        c_p['measurement_name'] + '-' + str(now.hour) + '-' + str(now.minute) +\
        '-' + str(now.second) + '.npy'
    np.save(phasemask_name, c_p['phasemask'], allow_pickle=True)


def move_particles_slowly(last_d=30e-6):
    # Function for moving the particles between the center and the edges
    # without dropping then
    global c_p
    if last_d>40e-6 or last_d<0:
        print('Too large distance.')
        return
    if last_d>c_p['trap_separation']:
        while c_p['trap_separation']<last_d:
            if c_p['new_phasemask']==False:
                if last_d - c_p['trap_separation'] < 1e-6:
                    c_p['trap_separation'] = last_d
                else:
                    c_p['trap_separation'] += 1e-6
                c_p['new_phasemask'] = True
                print(c_p['trap_separation'])
                time.sleep(0.5)
            time.sleep(1)
    else:
        while c_p['trap_separation']>last_d:
            if c_p['new_phasemask']==False:
                if c_p['trap_separation'] - last_d < 1e-6:
                    c_p['trap_separation'] = last_d
                else:
                    c_p['trap_separation'] -= 1e-6
                c_p['new_phasemask'] = True
                print(c_p['trap_separation'])
                time.sleep(0.5)
            time.sleep(1)
    return


############### Main script starts here ####################################
c_p = get_default_c_p()
c_p['camera_model'] = 'ThorlabsCam'
# Create camera and set defaults
# global image
# if c_p['camera_model'] == 'ThorlabsCam':
#     image = np.zeros((c_p['AOI'][1]-c_p['AOI'][0], c_p['AOI'][3]-c_p['AOI'][2], 1))
# else:
#     image = np.zeros((672,512,1))

# Create a empty list to put the threads in
thread_list = []
d0x = -80e-6
d0y = -80e-6

# Define experiment to be run. Can also be read from a file nowadays.
xm1, ym1 = SLM.get_xm_ym_rect(nbr_rows=2, nbr_columns=1, d0x=d0x, d0y=d0y, dx=20e-6, dy=20e-6,)
experiment_schedule = [
{'xm':xm1, 'ym':ym1, 'use_LGO':[False],'target_experiment_z':1000,
'LGO_order':4,  'recording_duration':1000,'SLM_iterations':30,'activate_traps_one_by_one':False},
]

c_p['experiment_schedule'] = experiment_schedule
T_D = UserInterface(tkinter.Tk(), "Control display", c_p, thread_list)

sys.exit()