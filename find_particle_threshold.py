import cv2
import numpy as np
from matplotlib import pyplot as plt
import scipy.ndimage as ndi
from skimage import measure
import time
from numba import njit, jit


@njit(parallel=True)
def parallel_center_of_masses(data):
    # Without "parallel=True" in the jit-decorator
    # the prange statement is equivalent to range
    ret_x = []
    ret_y = []
    for d in data:
        #ret.append(center_of_mass(d))
        pos = np.nonzero(d)
        tot = len(d[0])#np.sum(d)
        #tot = np.shape(pos)[1]
        x = np.sum(pos[0][:]) # check if these two calculations can be exchanged for one
        y = np.sum(pos[1][:])
        ret_x.append(x/tot)
        ret_y.append(y/tot)
    return ret_x, ret_y

def find_single_particle_center(img,threshold=127):
    """
    Locate the center of a single particle in an image.
    Obsolete now, find_particle_centers is surperior in every way
    """
    img_temp = cv2.medianBlur(img,5)
    ret,th1 = cv2.threshold(img_temp,threshold,255,cv2.THRESH_BINARY)
    cy, cx = ndi.center_of_mass(th1)
    # if np.isnan(cx) return inf?
    return cx,cy,th1
def threshold_image(image,threshold=120,bright_particle=True):
        img_temp = cv2.medianBlur(image,5)
        if bright_particle:
            ret,thresholded_image = cv2.threshold(img_temp,threshold,255,cv2.THRESH_BINARY)
            return thresholded_image
        else:
            ret,thresholded_image = cv2.threshold(img_temp,threshold,255,cv2.THRESH_BINARY_INV)
            return thresholded_image

def find_groups_of_interest(counts, particle_upper_size_threshold, particle_size_threshold, separate_particles_image):
    '''
    Exctract the particles into separate images to be center_of_massed in parallel
    '''
    particle_images = []
    #target_groups = []
    for group, pixel_count in enumerate(counts): # First will be background
        if particle_upper_size_threshold>pixel_count>particle_size_threshold:
            #target_groups.append(group)
            particle_images.append(separate_particles_image==group)
    return particle_images


def get_x_y(counts, particle_upper_size_threshold, particle_size_threshold, separate_particles_image):
    x = []
    y = []
    for group, pixel_count in enumerate(counts): # First will be background
        if particle_upper_size_threshold>pixel_count>particle_size_threshold:
            # TODO: Parallelize this thing
            # Particle found, locate center of mass of the particle
            cy, cx = ndi.center_of_mass(separate_particles_image==group)

            x.append(cx)
            y.append(cy)
    return x, y

#@jit
def find_particle_centers(image,threshold=120,particle_size_threshold=200,particle_upper_size_threshold=5000,bright_particle=True):
    """
    Function which locates particle centers using thresholding.
    Parameters :
        image - Image with the particles
        threshold - Threshold value of the particle
        particle_size_threshold - minimum area of particle in image measured in pixels
        bright_particle - If the particle is brighter than the background or not
    Returns :
        x,y - arrays with the x and y coordinates of the particle in the image in pixels.
            Returns empty arrays if no particle was found
    """

    # Do thresholding of the image
    thresholded_image = cv2.medianBlur(image, 5) > threshold # Added thresholding here

    # Separate the thresholded image into different sections
    separate_particles_image = measure.label(thresholded_image)
    # use cv2.findContours instead?
    # Count the number of pixels in each section
    counts = np.bincount(np.reshape(separate_particles_image,(np.shape(separate_particles_image)[0]*np.shape(separate_particles_image)[1])))

    x = []
    y = []
    #group = 0

    # Check for pixel sections which are larger than particle_size_threshold.
    # particle_images = find_groups_of_interest(counts, \
    #                                           particle_upper_size_threshold, \
    #                                           particle_size_threshold, \
    #                                           separate_particles_image)
    # x, y = parallel_center_of_masses(particle_images)

    # TODO Calcualte image-moments to determine shape
    for group, pixel_count in enumerate(counts): # First will be background
        if particle_upper_size_threshold>pixel_count>particle_size_threshold:
            # Particle found, locate center of mass of the particle
            cy, cx = ndi.center_of_mass(separate_particles_image==group) # This is slow
            x.append(cx)
            y.append(cy)


    return x, y, thresholded_image
