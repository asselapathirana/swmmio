import pandas as pd
import shutil
import os
import fileinput
import itertools
from datetime import datetime
from swmmio.swmmio import Model
from swmmio.utils import functions as funcs
from swmmio.utils.dataframes import create_dataframeINP
from swmmio.utils import swmm_utils as su
from swmmio.version_control import utils as vc_utils
#from .utils.text import * #functions for processing inp/rpt/txt files

pd.options.display.max_colwidth = 200


def copy_model(basemodel, branch_name, newdir=None):

    """
    takes a swmmio model object, create a new inp
    returns a swmmio Model object
    """

    #create new directory and copy base inp
    safename = branch_name.replace(" ", '-')
    if not newdir:
        wd = basemodel.inp.dir
        newdir = os.path.join(wd, safename)
        if not os.path.exists(newdir):
            os.makedirs(newdir)
        else:
            return "branch or directory already exists"

    shutil.copyfile(basemodel.inp.filePath, os.path.join(newdir, safename + '.inp'))
    new_branch = Model(newdir)

    return new_branch

def create_combinations(baseline_dir, genres_dir, combi_dir):

    """
    given a set of segmented models (model genres), this function combines
    models in all logical combinations.
    """


    genres = os.listdir(genres_dir)
    flavors = []
    for gen in genres:
        for flav in os.listdir(os.path.join(genres_dir, gen)):
            #print os.path.join(gen, flav)
            flavors.append(os.path.join(gen, flav))

    newmodels = []
    basemodel = Model(baseline_dir)
    #creat directories for new model combinations
    for L in range(1, len(flavors)+1):
      for subset in itertools.combinations(flavors, L):


        #newcombi = '_'.join(subset)
        newcombi = '_'.join([os.path.split(s)[1] for s in subset])
        new_combi_dir = os.path.join(combi_dir, newcombi)

        #create a list of the parent directories, use that to prevent
        #two or more from same genre
        genredirs = [os.path.split(s)[0] for s in subset]
        if len(genredirs) == len(set(genredirs)) and len(subset) > 1:
                #confirming the list length is equal to the set length (hashable)
                #confirms that there are not duplicates in the items list

            if not os.path.exists(new_combi_dir):#and newcombi not in flavors:
                #check to make sure new model doesn't repeat two or more from
                #a particular genre.
                print new_combi_dir
                os.mkdir(new_combi_dir)
                newmodels.append(new_combi_dir)

                #create the new model
                model_objects = [Model(os.path.join(genres_dir, f)) for f in subset]
                merge_models(basemodel, newdir=new_combi_dir, parent_models=model_objects)

def merge_models(basemodel, newdir, parent_models):

    """
    create new model based on a given basemodel and optionally a list of
    parent models (models to inherit changes from with resprect to the base model).

    overwrite_sections is an option dictionary with keys matching seciton headers and
    values being a dataframe with data to be substituted into the new model. If the
    overwrite section is not found in the original model, it is inserted at the end.
    """

    newname = '_'.join([x.inp.name for x in parent_models])# + "_" + funcs.random_alphanumeric(3)
    print 'Building new model by combining models: {}'.format(', '.join([x.inp.name for x in parent_models]))

    #new_branch = copy_model(basemodel, branch_name = newname, newdir=newdir)
    newinpfile = os.path.join(newdir, newname +'.inp')

    #ignore certain problematic sections and simply copy it from the basemodel
    blindcopies = ['[CURVES]', '[TIMESERIES]', '[RDII]', '[HYDROGRAPHS]']

    #with open (new_branch.inp.filePath, 'w') as f:
    with open (newinpfile, 'w') as f:

        #create the MS Excel writer object
        xlpath = os.path.join(newdir, newname + '.xlsx')
        excelwriter = pd.ExcelWriter(xlpath)
        vc_utils.create_info_sheet(excelwriter, basemodel, parent_models)

        #compute the changes for each model from the basemodel
        allheaders = funcs.complete_inp_headers(basemodel.inp.filePath)
        for section in allheaders['order']:

            if section not in blindcopies:
                #if this section is not a known problematic section, process as normal
                changes = [Change(basemodel, m, section) for m in parent_models]
                new_section = apply_changes(basemodel, changes, section=section)

            else:
                #blindly copy this section from the base model
                new_section = create_dataframeINP(basemodel.inp, section=section)

            #write the section into the inp file and the excel file
            vc_utils.write_section(f, excelwriter, allheaders, section, new_section)


        excelwriter.save()

    return Model(newinpfile)



def apply_changes(model, changes, section='[JUNCTIONS]'):

    df1 = create_dataframeINP(model.inp, section)
    #rmvs = pd.concat([c.removed for c in changes] + [c.altered for c in changes])

    #df of elements to be commented out in new inp,
    #(those altered [to be replaceed by new row] or those deleted)
    tobecommented = pd.concat([c.removed for c in changes])
    tobealtered = pd.concat([c.altered for c in changes])
    ids_to_remove_from_df1 = tobecommented.index | tobealtered.index #union of altered and removed indices
    tobecommented.index = ["; " + str(x) for x in tobecommented.index] #add comment character

    #add rows for new elements and altered element
    adds = pd.concat([c.added for c in changes] + [c.altered for c in changes])
    df2 = df1.drop(ids_to_remove_from_df1)

    newdf = pd.concat([df2, tobecommented, adds])

    return newdf

class Change(object):

    def __init__(self, model1, model2, section='[JUNCTIONS]'):

        df1 = create_dataframeINP(model1.inp, section)
        df2 = create_dataframeINP(model2.inp, section)
        added_ids = df2.index.difference(df1.index)
        removed_ids = df1.index.difference(df2.index)

        #find where elements were changed (but kept with same ID)
        common_ids = df1.index.difference(removed_ids) #original - removed = in common
        #both dfs concatenated, with matched indices for each element
        full_set = pd.concat([df1.ix[common_ids], df2.ix[common_ids]])
        #drop dupes on the set, all things that did not changed should have 1 row
        changes_with_dupes = full_set.drop_duplicates()
        #duplicate indicies are rows that have changes, isolate these
        changed_ids = changes_with_dupes.index.get_duplicates()

        added = df2.ix[added_ids]
        added['Comment'] = '; Added from model {}'.format(model2.inp.filePath)

        altered = df2.ix[changed_ids]
        altered['Comment'] = '; Altered in model {}'.format(model2.inp.filePath)

        removed = df1.ix[removed_ids]
        #comment out the removed elements
        #removed.index = ["; " + str(x) for x in removed.index]
        removed['Comment'] = '; Removed in model {}'.format(model2.inp.filePath)

        self.old = df1
        self.new = df2
        self.added = added
        self.removed = removed
        self.altered = altered
        #self.altered['Comments'] == 'Items changed from model {}'.format(model2.inp.filePath)