import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import re
import demoji
import string
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix
from sklearn.feature_extraction.text import CountVectorizer 
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.pipeline import Pipeline
from sklearn.pipeline import Pipeline
import pickle


with open('LRmodel_pipe_cyberbullying.pkl','rb') as f:
  pipe_model=pickle.load(f)

def evaluate(text, pipe_model):
  if type(text)==str:
    text=[text]
  output = pipe_model.predict(text)
  return output

print(evaluate("You are a good Christian man",pipe_model))