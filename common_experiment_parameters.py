# File with common experiment parameters.
from datetime import datetime
import numpy as np

def get_save_path(base_path='F:/Martin/D', extension_path=""):
    now = datetime.now()
    recording_path = base_path + str(now.year) \
        + '-' + str(now.month) + '-' + str(now.day)
    recording_path = recording_path + extension_path if len(extension_path) > 0 else recording_path
    print(recording_path)
    try:
        os.mkdir(recording_path)
    except:
        print('Directory already exist')
    return recording_path


def get_experiment_setup():
    '''
    Function which returns the standard parameters which need to be calibrated
    before an experiment.
    '''
    params = {
        'phasemask_width' : 1080,
        'phasemask_height' : 1080,
        'phasemask_position' : 2340,
        'slm_x_center': 558,# needs to be recalibrated if camera is moved.
        # This is the position of the 0th order of the SLM (ie where the trap)
        # with xm=ym=0 is located in camera coordinates
        'slm_y_center': 576,#605-29,
        'slm_to_pixel':5000000, # Basler
        #4550000.0, #thorlabs
        'x_comp':3.2e4, # compensates for shift in x,y coordninates when
        # changing z of trap with slm. Needs to be calibrated.
        'y_comp':9e4,
    }
    return params


def set_defualt_trap_position(c_p):
    # Initialize traps and set traps positions
    c_p['traps_absolute_pos'] = np.zeros((2,1))
    c_p['traps_relative_pos'] = np.zeros((2,1))

    # Position of first trap
    c_p['xm'] = [100]
    c_p['ym'] = [200]

    c_p['traps_absolute_pos'][0][0] = 100
    c_p['traps_absolute_pos'][1][0] = 200
    c_p['traps_relative_pos'][0][0] = c_p['traps_absolute_pos'][0][0]
    c_p['traps_relative_pos'][1][0] = c_p['traps_absolute_pos'][1][0]

    # Convert xm,ym to slm coordinates.
    c_p['xm'] = [((x - c_p['slm_x_center']) / c_p['slm_to_pixel']) for x in c_p['xm']]
    c_p['ym'] = [((x - c_p['slm_y_center']) / c_p['slm_to_pixel']) for x in c_p['ym']]

    c_p['zm'] = np.zeros(len(c_p['xm']))


def get_default_c_p(recording_path=None):
    '''
    Dictionary containing primarily parameters used for specifying the
    experiment and synchronizing
    the program threads, such as current trap and motor serial numbers.
    '''
    # TODO : Consider to change this into a class.
    # Make this object possible to pickle and unpickle to make it easier to
    # reuse settings.
    # TODO: Replace xm,ym, zm with single array or similar. Potentilly by
    # Removing them completely and having only pixel coordinates in the code
    # And converting on the fly for the SLM.
    if recording_path is None:
        recording_path = get_save_path()
    c_p = {
        'serial_nums_motors': ['27502438','27502419','97100532'],# x,y,z
        'channel': 1,
        'network_path': 'G:/',
        'recording_path': recording_path,
        'polling_rate': 100,
        'program_running': True,  # True if camera etc should keep updating
        'motor_running': True,  # Should the motor thread keep running
        'zoomed_in': False,  # Keeps track of whether the image is cropped or
        # not
        'recording': False,  # True if recording is on
        'AOI': [0, 672, 0, 512], # Default for basler camera [0,1200,0,1000] TC
        'image': np.zeros((1080,1080,1)),
        'new_settings_camera': False,
        'new_AOI_display': False,
        'new_phasemask': False,
        'phasemask_updated': False,  # True if the phasemask is to be udpated
        'SLM_iterations': 30,
        'movement_threshold': 30,
        'nbr_experiments':1,
        'framerate': 500,
        'tracking_on': False,
        'setpoint_temperature': 25,
        'current_temperature': 25,
        'starting_temperature': 25,
        'temperature_controller_connected': False,
        'temperature_stable': False,
        'temperature_output_on':True,
        'need_T_stable':False,
        'search_direction': 'up',
        'particle_centers': [[500], [500]],
        'target_particle_center': [500, 500],  # Position of the particle we
        # currently are trying to trap. Used to minimize changes in code when
        # updating to multiparticle tracking.
        'target_trap_pos': [500, 500],
        'motor_movements': [0, 0],  # How much x and y motor should be moved
        'motor_starting_pos': [0, 0],  # Startng position of x-y motors,
        # needed for z-compensation
        'motor_current_pos': [0, 0, 0],  # Current position of x-y motors,
        # needed for z-compensation, z is the last
        'motors_connected':[False, False, False],
        'connect_motor':[True, True, True],
        'z_starting_position': 0,  # Where the experiments starts in z position
        'z_movement': 0,  # Target z-movement in "ticks" positive for up,
        # negative for down
        'target_experiment_z': 150,  # height in ticks at which experiment should
        # be performed
        'z_x_diff': 0,  # Used for compensating drift in z when moving the
        # sample. Caused by sample being slightly tilted Needs to be calibrated
        # calculated as the change needed in z (measured in steps) when the
        # motor is moved 1 mm in positive direction z_x_diff = (z1-z0)/(x1-x0) steps/mm
        # Sign ,+ or -,of this?
        'z_y_diff': 0, # approximate, has not measured this
        'x_start': 0,
        'temperature_z_diff': 0,#-180, #-80,  # How much the objective need to be moved
        # in ticks when the objective is heated 1C. Needs to be calibrated manually.
        # to compensate for the changes in temperature.Measured in
        # [ticks/deg C]

        'slm_x_center': 558,#Calibrated 07/08/2020.
        # Needs to be recalibrated if camera is moved.
        # This is the position of the 0th order of the SLM (ie where the trap)
        # with xm=ym=0 is located in camera pixel coordinates
        'slm_y_center': 576,
        # 'slm_to_pixel': 5000000.0, # Basler
        # #4550000.0,# Thorlabs

        'return_z_home': False,
        'focus_threshold':1_000, #
        'particle_threshold': 100,
        'particle_size_threshold': 200,  # Parcticle detection threshold
        'bright_particle': True,  # Is particle brighter than the background?
        'xy_movement_limit': 1200,
        #'motor_locks': [threading.Lock(), threading.Lock()],

        'use_LGO':[False],
        'LGO_order': -8,
        'nbr_ghost_traps':0,
        # Ghost-traps: traps to be added after particle(s) are lifted to
        # make comparison measurements
        'exposure_time':80, # ExposureTime in micro s
        'SLM_iterations':5,
        'trap_separation_x':20e-6,
        'trap_separation_y':20e-6,
        'new_video':False,
        'recording_duration':3000,
        'experiment_schedule':[],
        'measurement_name':'', # Name of measurement to use when saving data.
        'experiment_progress':0, # number of experiments run
        'experiment_runtime':0, # How many seconds have the experiment been running
        'activate_traps_one_by_one':False, # If true then the program will
        # activate and fill traps one by one.
        'camera_model':'basler',
        'cell_width':32,  # Width of cells when dividing the frame into a grid
        # for the path-search
    }

    # Add camera dependent parameters.
    c_p['mmToPixel'] = 17736 if c_p['camera_model'] == 'basler' else 16140
    c_p['slm_to_pixel'] = 5_000_000 if c_p['camera_model'] == 'basler' else 4_550_000

    # Initialize traps and set traps positions
    set_defualt_trap_position(c_p)

    c_p['traps_occupied'] = [False for i in range(len(c_p['traps_absolute_pos'][0]))]
    c_p['phasemask'] = np.zeros((1080, 1080))  # phasemask  size

    return c_p


def get_motor_default_control_parameters():
    pass