"""
Testing model responses to structured stimuli
"""
import matplotlib.pyplot as plt
import numpy as np
from . import stimuli as stim
from tqdm import tqdm


def two_flashes(model):
    """Generates responses to a pair of neighboring flashes"""
    # get the paired flash stimulus
    stim = paired_flashes(ifi=2, duration=1, intensity=-1., padding=45)

    # pass it through the model
    resp = model.predict(stim)

    # get a 1-D trace of the stimulus
    stim_trace = stim[:, -1, 0, 0].copy()
    time = np.arange(stim_trace.size) * 0.01

    # plot the stimulus and responses
    fig = plt.figure(figsize=(8, 6))
    ax0 = plt.subplot2grid((5, 1), (0, 0))
    ax1 = plt.subplot2grid((5, 1), (1, 0), rowspan=4)
    ax0.plot(time, stim_trace, 'k-')
    ax0.set_ylabel('Stimulus')
    ax0.set_xlim(0, 0.5)
    ax0.set_xticks([])
    ax1.plot(time, resp, '-')
    ax1.set_ylabel('Firing rate (Hz)')
    ax1.set_xlabel('Time (s)')
    ax1.set_xlim(0, 0.5)
    plt.show()
    plt.draw()

    return fig, ax0, ax1


def oms(duration=4, sample_rate=0.01, transition_duration=0.07, silent_duration=0.93,
        magnitude=5, space=(50, 50), center=(25, 25), object_radius=5, coherent=False, roll=False):
    """
    Object motion sensitivity stimulus, where an object moves differentially
    from the background.

    INPUT:
    duration        movie duration in seconds
    sample_rate     sample rate of movie in Hz
    coherent        are object and background moving coherently?
    space           spatial dimensions
    center          location of object center
    object_width    width in pixels of object
    speed           speed of random drift
    motion_type     'periodic' or 'drift'
    roll            whether to roll_axis for model prediction

    OUTPUT:
    movie           a numpy array of the stimulus
    """
    # fixed params
    contrast = 1
    grating_width = 3

    transition_frames = int(transition_duration/sample_rate)
    silent_frames = int(silent_duration/sample_rate)
    total_frames = int(duration/sample_rate)

    # silence, one direction, silence, opposite direction
    obj_position = np.hstack([np.zeros((silent_frames,)), np.linspace(0, magnitude, transition_frames),
                            magnitude*np.ones((silent_frames,)), np.linspace(magnitude, 0, transition_frames)])

    half_silent = silent_frames/2
    back_position = np.hstack([obj_position[half_silent:], obj_position[:-half_silent]])

    # make position sequence last total_frames
    if len(back_position) > total_frames:
        print("Warning: movie won't be {} shorter than a full period.".format(np.float(2*transition_frames + 2*silent_frames)/total_frames))
        back_position[:total_frames]
        obj_position[:total_frames]
    else:
        reps = np.ceil(np.float(total_frames)/len(back_position))
        back_position = np.tile(back_position, reps)[:total_frames]
        obj_position = np.tile(obj_position, reps)[:total_frames]

    # create a larger fixed world of bars that we'll just crop from later
    padding = 2*grating_width + magnitude
    fixed_world = -1*np.ones((space[0], space[1]+padding))
    for i in range(grating_width):
        fixed_world[:, i::2 * grating_width] = 1

    # make movie
    movie = np.zeros((total_frames, space[0], space[1]))
    for frame in range(total_frames):
        # make background grating
        background_frame = np.copy(fixed_world[:,back_position[frame]:back_position[frame]+space[0]])

        if not coherent:
            # make object frame
            object_frame = np.copy(fixed_world[:,obj_position[frame]:obj_position[frame]+space[0]])

            # set center of background frame to object
            object_mask = cmask(center, object_radius, object_frame)
            background_frame[object_mask] = object_frame[object_mask]

        # adjust contrast
        background_frame *= contrast
        movie[frame] = background_frame

    if roll:
        # roll movie axes to get the right shape
        roll_movies = rolling_window(movie, 40)
        return roll_movies
    else:
        return movie


def osr(duration, interval, nflashes, intensity=-1.):
    """Omitted stimulus response

    Usage
    -----
    >>> stim = osr(2, 20, 5)

    Parameters
    ----------
    duration : float
        The duration of a flash, in samples

    frequency : int
        The inter-flash interval, in samples

    nflashes : int
        The number of flashes to repeat before the omitted flash
    """
    single_flash = flash(duration, interval, interval * 2, intensity=intensity)
    omitted_flash = flash(duration, interval, interval * 2, intensity=0.0)
    flash_group = list(repeat(single_flash, nflashes))
    zero_pad = np.zeros((interval, 1, 1))
    return concat(zero_pad, *flash_group, omitted_flash, *flash_group, nx=50, nh=40)


def motion_anticipation(km):
    """Generates the Berry motion anticipation stimulus

    Stimulus from the paper:
    Anticipation of moving stimuli by the retina,
    M. Berry, I. Brivanlou, T. Jordan and M. Meister, Nature 1999

    Parameters
    ----------
    km : keras.Model

    Returns
    -------
    motion : array_like
    flashes : array_like
    """
    velocity = 0.08         # 0.08 bars/frame == 0.44mm/s, same as Berry et. al.
    width = 2               # 2 bars == 110 microns, Berry et. al. used 133 microns
    flash_duration = 2      # 2 frames == 20 ms, Berry et. al. used 15ms

    # moving bar stimulus and responses
    c_right, stim_right = stim.driftingbar(velocity, width)
    resp_right = km.predict(stim_right)

    c_left, stim_left = stim.driftingbar(-velocity, 2)
    resp_left = km.predict(stim_left)
    max_drift = resp_left.max()

    # flashed bar stimulus
    flash_centers = np.arange(-25, 26)
    flashes = (stim.flash(flash_duration, 48, 100, intensity=stim.bar((x, 0), width, 50))
               for x in flash_centers)

    # flash responses are a 3-D array with dimensions (centers, stimulus time, cell)
    flash_responses = np.stack([km.predict(stim.concat(f)) for f in tqdm(flashes)])

    # pick off the flash responses at a particular time point
    resp_flash = flash_responses.mean(axis=2)[:, 14]
    max_flash = flash_responses.max()

    # generate the figure
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111)
    ax.plot(c_left[40:], resp_left.mean(axis=1) / max_drift, 'g-', 'Left motion')
    ax.plot(c_right[40:], resp_right.mean(axis=1) / max_drift, 'b-', 'Right motion')
    ax.plot(flash_centers, resp_flash / max_flash, 'r-', label='Flash')

    return (fig, ax), (c_right, stim_right, resp_right), (c_left, stim_left, resp_left), (flash_centers, flash_responses)