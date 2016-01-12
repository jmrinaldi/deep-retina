import numpy as np
import theano
import h5py
import tableprint
from keras.models import model_from_json
from scipy.stats import pearsonr
from preprocessing import datagen, loadexpt

def load_model(model_path, weight_filename):
	''' Loads a Keras model using:
			- an architecture.json file
			- an h5 weight file, for instance 'epoch018_iter01300_weights.h5'
			
		INPUT:
			model_path		the full path to the saved weight and architecture files, ending in '/'
			weight_filename	an h5 file with the weights
        OUTPUT:
            returns keras model
	'''
	architecture_filename = 'architecture.json'
	architecture_data = open(model_path + architecture_filename, 'r')
	architecture_string = architecture_data.read()
	model = model_from_json(architecture_string)
	model.load_weights(model_path + weight_filename)
	
	return model


def load_partial_model(model, layer_id):
    '''
    Returns the model up to a specified layer.

    INPUT:
        model       a keras model
        layer_id    an integer designating which layer is the new final layer

    OUTPUT:
        a theano function representing the partial model
    '''

    # create theano function to generate activations of desired layer
    return theano.function([model.layers[0].input], model.layers[layer_id].get_output(train=False))


def list_layers(model_path, weight_filename):
    '''
    Lists the layers in the model with their children.
    
    This provides an easy way to see how many "layers" in the model there are, and which ones
    have weights attached to them.

    Layers without weights and biases are relu, pool, or flatten layers.

    INPUT:
			model_path		the full path to the saved weight and architecture files, ending in '/'
			weight_filename	an h5 file with the weights
    OUTPUT:
            an ASCII table using tableprint
    '''
    weights = h5py.File(model_path + weight_filename, 'r')
    layer_names = list(weights)

    # print header
    print(tableprint.hr(3))
    print(tableprint.header(['layer', 'weights', 'biases']))
    print(tableprint.hr(3))

    params = []
    for l in layer_names:
        params.append(list(weights[l]))
        if params[-1]:
            print(tableprint.row([l.encode('ascii','ignore'), params[-1][0].encode('ascii','ignore'),
                params[-1][1].encode('ascii','ignore')]))
        else:
            print(tableprint.row([l.encode('ascii','ignore'), '', '']))

    print(tableprint.hr(3))


def get_test_responses(model, stim_type='natural', cells=[0]):
    '''
        Get a list of [true_responses, model_responses] on the same test data.
    '''
    if stim_type is 'natural':
        test_data = loadexpt(cells, 'naturalscene', 'test', 40)
    elif stim_type is 'white':
        test_data = loadexpt(cells, 'whitenoise', 'test', 40)

    truth = []
    predictions = []
    for X, y in datagen(50, *test_data):
        truth.extend(y)
        predictions.extend(model.predict(X))

    truth = np.array(truth)
    predictions = np.array(predictions)

    return [truth, predictions]

def cc(r, rhat):
    """
    Correlation coefficient
    """
    return np.corrcoef(np.vstack((rhat, r)))[0, 1]


def lli(r, rhat):
    """
    Log-likelihood improvement over a mean rate model (in bits per spike)
    """

    mean = np.mean(rhat)
    mu = float(np.mean(r * np.log(mean) - mean))
    return (np.mean(r * np.log(rhat) - rhat) - mu) / (mean * np.log(2))


def rmse(r, rhat):
    """
    Root mean squared error
    """
    return np.sqrt(np.mean((rhat - r) ** 2))


def fev(r, rhat):
    """
    Fraction of explained variance
    """

    mean = np.mean(r)
    rate_var = np.mean((mean - r) ** 2)
    return 1.0 - (rmse(r, rhat) ** 2) / rate_var


def get_correlation(model, stim_type='natural', cells=[0]):
    '''
        Get Pearson's r correlation.
    '''
    truth, predictions = get_test_responses(model, stim_type=stim_type, cells=cells)

    test_cc = []
    for c in cells:
        test_cc.append(pearsonr(truth[:,c], predictions[:,c])[0])

    return test_cc


def get_performance(model, stim_type='natural', cells=[0], metric='pearsonr'):
    '''
        Get correlation coefficient on held-out data for deep-retina.

        INPUT:
            model           Keras model
            stim_type       'natural' or 'white'; which test data to draw from?
            cells           list of cell indices
            metric          'pearsonr' (scipy Pearson's r), 
                            'cc' (numpy's corrcoef),
                            'lli' (Log-likelihood improvement over a mean rate model in bits per spike),
                            'rmse' (Root mean squared error),
                            'fev' (Fraction of explained variance; note this does not take into account
                                    the variance from trial-to-trial)
    '''
    truth, predictions = get_test_responses(model, stim_type=stim_type, cells=cells)

    test_cc = []
    for c in cells:
        if metric is 'pearsonr':
            test_cc.append(pearsonr(truth[:,c], predictions[:,c])[0])
        elif metric is 'cc':
            test_cc.append(cc(truth[:,c], predictions[:,c]))
        elif metric is 'lli':
            test_cc.append(lli(truth[:,c], predictions[:,c]))
        elif metric is 'rmse':
            test_cc.append(rmse(truth[:,c], predictions[:,c]))
        elif metric is 'fev':
            test_cc.append(fev(truth[:,c], predictions[:,c]))
        

    return test_cc

def get_weights(path_to_weights, layer_name='layer_0'):
    '''
        A simple function to return the weights from a saved .h5 file.
    '''
    
    weight_file = h5py.File(path_to_weights, 'r')

    # param_0 stores the weights, param_1 stores biases
    weights = weight_file[layer_name]['param_0']
    return weights

