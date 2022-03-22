# -*- coding: utf-8 -*-
"""
Regression Systematic Error
***************************
"""

#%%
# Imports
# =======

from deepchecks.tabular import Dataset
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.datasets import load_diabetes
from sklearn.model_selection import train_test_split
from deepchecks.tabular.checks.performance import RegressionSystematicError

#%%
# Generating data
# ===============

diabetes_df = load_diabetes(return_X_y=False, as_frame=True).frame
train_df, test_df = train_test_split(diabetes_df, test_size=0.33, random_state=42)
train_df['target'] = train_df['target'] + 150

train = Dataset(train_df, label='target', cat_features=['sex'])
test = Dataset(test_df, label='target', cat_features=['sex'])

clf = GradientBoostingRegressor(random_state=0)
_ = clf.fit(train.data[train.features], train.data[train.label_name])

#%%
# Running RegressionSystematicError check
# =======================================

check = RegressionSystematicError()

#%%

check.run(test, clf)
