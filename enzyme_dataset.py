# -*- coding: utf-8 -*-
"""Novoenzymes_Dataset.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/14ZHsjuW59jD7kc8v5dOGZs1r3Qu5evU5
"""

from tqdm import tqdm
import copy
import numpy as np
import pandas as pd
import itertools
from scipy.special import softmax
import torch
from torchmetrics import SpearmanCorrCoef

# ===== Utils =====

# Set of possible Amino-Acids
AA_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'K', 'L', 'M', 'N',
       'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']

def group_mutations(df, max_rate):
  """
  Finds protein sequences that are mutations to each other and assigns them 
  the same number of group.
  - df: the dataframe which contains the following columns "protein_sequence",
  - max_rate: maximum percentage of different amino-acids between two mutants 
              of the same group 
  """
  # Dataframe to count amino-acid occurences
  df_count = pd.DataFrame(columns = AA_letters)

  # Loop over amino-acids
  for aa in AA_letters:
    df_count[aa] = df["protein_sequence"].str.count(aa)
  
  # Get length
  df_count["len"] = df_count.sum(axis = 1).astype(int)
  # Get sequence
  df_count["sequence"] = df["protein_sequence"]
  
  # Series to set groups
  s_groups = pd.Series(np.nan, index = df.index)

  # To check efficiency
  filtered = 0

  # Initializing group_id
  group_id = 0
  # List of processed proteins
  idx_out = [] 
  # List of all proteins to loop over
  idx_all = df_count.index.values
  # Loop over proteins
  for id in tqdm(idx_all):

    # Already belongs to a group 
    if id in idx_out:
      continue

    # Get the reference protein
    prot = df_count.loc[id]
    # Search for substitutions i.e. same lengths
    df_sub = df_count[df_count["len"] == prot["len"]].drop(id)
    
    # No mutations
    if len(df_sub) == 0:
      idx_out.append(id)
      continue
    
    # Compare sequences
    dist = character_distance(prot, df_sub)
    # Filter differences larger then max_rate
    df_sub = df_sub[dist<max_rate]
    filtered += (dist<max_rate).sum()
    
    # Compare character by character
    n_mutations = 0
    prot_sequence = prot["sequence"]
    prot_len = prot["len"]
    for sub_id, sub in df_sub.iterrows():
      sub_sequence = sub["sequence"]
      # Count differences
      diff = 0
      for i in range(prot_len): 
        if prot_sequence[i] != sub_sequence[i]:
          diff += 1
      # Keep if diff < max_rate
      if diff/prot_len < max_rate:
        # If group exists
        if sub_id in idx_out:
          group_id = s_groups[sub_id]
        # It is a new mutation
        n_mutations += 1
        s_groups[sub_id] = group_id
        # Remove protein from list of ids
        idx_out.append(sub_id)

  	# Assign group to reference
    if n_mutations != 0:
      s_groups[id] = group_id
      # Deal with group numbering
      if group_id == 0 or group_id == s_groups.max():
        group_id += 1
      else:
        group_id = s_groups.max() + 1

    idx_out.append(id)

  print(f"\nFiltered: {filtered}")
  return s_groups


def locate_mutations(df):
  """
  Picks reference protein in a mutation group and returns locations of mutation 
  for other proteins with repsect to reference
  """

  locations = {}

  for group_id, group in df.groupby("sub_group"):
    # Select a reference
    if len(group) == 2:
      prot_ref = group.sample(n=1)
    else:
      # Choose the median between multiple mutations
      median = group["tm"].median()
      prot_ref = group.iloc[[np.argmin(np.abs(group["tm"] - median))]]
    group = group.drop(prot_ref.index)
    # Compare all other proteins to median
    prot_seq_ref = prot_ref["protein_sequence"].item()
    for prot_other_id, prot_other in group.iterrows():
      diff_loc = []
      prot_other_seq = prot_other["protein_sequence"]
      for i in range(prot_ref["len"].item()):
        if prot_other_seq[i] != prot_seq_ref[i]:
          diff_loc.append(i)
      if len(diff_loc) > 0:
        locations[prot_other_id] = diff_loc

  s_locations = pd.Series(locations)
  return s_locations

def split_group(df, frac_val, frac_test, power = 1/6):
  """
  Split by group size
  - df: dataframe with column "sub_group"
  - frac_val: fraction of data for validation 
  - frac_test: fraction of data for test
  - power: Number between 0 and 1, to better split the groups.
  """
  n_tot = len(df)
  
  group_counts = df["sub_group"].value_counts()
  group_counts_dampened = np.power(
      group_counts - group_counts.min(), power).round(1)
  # Sample validation 0.15
  group_val = group_counts.groupby(group_counts_dampened).sample(
          frac = frac_val, random_state = 0)
  df.loc[np.isin(df["sub_group"], group_val.index), "split"] = "val"
  group_counts = group_counts.drop(group_val.index)
  # Sample test
  frac_test = frac_test/(1-frac_val)
  group_test = group_counts.groupby(group_counts_dampened).sample(
          frac = frac_test, random_state = 0)
  df.loc[np.isin(df["sub_group"], group_test.index), "split"] = "test"
  # Set remaining as train
  group_counts = group_counts.drop(group_test.index)
  df.loc[np.isin(df["sub_group"], group_counts.index), "split"] = "train"

  return df

def split_tm(df, frac_val, frac_test, mask = None):
  n_tot = len(df)
  if mask is None:
    mask = [True]*len
  # Group into bins
  bins_tm= df.loc[mask, "tm"]//2
  # Sample validation 0.15
  idx_val = df.loc[mask].groupby(bins_tm).sample(frac = frac_val, 
                                                 random_state = 0).index
  df.loc[idx_val, "split"] = "val"
  mask = df["split"].isna()
  # Sample test
  idx_test = df.loc[mask].groupby(bins_tm).sample(
      frac = frac_test/(1-frac_val), random_state = 0).index
  df.loc[idx_test, "split"] = "test"
  df.loc[df["split"].isna()*mask, "split"] = "train"

  return df

def get_number_AA(prot_seq, settings):
  """
  Compute number of splits given settings.
  """
  if settings["truncate"] == "single":
    return settings["max_length"]
  
  if settings["truncate"] == "split":
    # Compute number of splits
    jump_length = int(settings["max_length"] * 
                      (1 - settings["overlap"]))
    n_splits = np.ceil((len(prot_seq) - 
                        settings["max_length"])/jump_length) + 1
    if settings["sample_splits"] is None:
      return int(n_splits * settings["max_length"])
      
    else:
      return int(settings["max_length"] * 
              min(n_splits, settings["sample_splits"]))
      
  if settings["truncate"] is None:
    return len(prot_seq)

def truncate_sequence(prot_seq, settings, diff_locations = None, T = 8):
  """
  Truncate sequences according to settings.
  - prot_seq: sequence of AA letters to truncate.
  - settings: dict containing max_length, truncate, overlap and sample_splits
  - diff_locations: locations with preferance to sample with high weight
  - T: weighting temperature, the higher, the more weight is given to the 
      diff_locations. T is a scalar multiplied by the weight before the softmax.
  """
  if diff_locations is not None:
    assert (np.array(diff_locations) < 0).sum() == 0, (
            "Locations cannot be negative.") 

  assert 0 <= settings["overlap"] < 1, "Overlap in [0,1]"

  # Random window
  if settings["truncate"] == "single":
    if diff_locations is not None:
      # Sample starting point around diff locations
      loc = np.random.choice(diff_locations)
      location_scale = settings["max_length"]//2
      sample_start = np.rint(np.random.normal(
          loc = max(0, loc - settings["max_length"]//2), 
                                            scale = location_scale))
      idx_start = int(np.clip(sample_start, 0, len(prot_seq) -1))
    else:
      # Sample randomly
      idx_start = np.random.randint(0, len(prot_seq) - 
                                  settings["max_length"] + 1)
      
    prot_seq_trunc = [prot_seq[idx_start:idx_start + 
                                settings["max_length"]]]

    aa_positions_ids = [np.arange(idx_start, idx_start + 
                                  settings["max_length"])]


  # Split sequence into multiple max_length windows
  if settings["truncate"] == "split":
   # Add unkown token to simulate [SEP] on both ends
    prot_seq = "X" + prot_seq + "X" 
    jump_length = int(settings["max_length"] * 
                      (1 - settings["overlap"]))
    
    stop_at = int(np.ceil((len(prot_seq) - 
                            settings["max_length"])/jump_length))
    idx_split = jump_length * np.arange(stop_at + 1)
    prot_seq_trunc = [prot_seq[j: j + settings["max_length"]] 
                               for j in idx_split]
    
    aa_positions_ids = [np.arange(j, min(j + settings["max_length"], 
                                         len(prot_seq))) for j in idx_split]
    
    n = len(prot_seq_trunc)

    if ((settings["sample_splits"] is not None) and 
        (n > settings["sample_splits"])):
      if diff_locations is not None and len(diff_locations)>0:
        # Sample starting point around diff locations
        weights = 0
        location_scale = settings["max_length"]//2
        for loc in diff_locations:
          weights += np.exp(- 0.5 * ((idx_split - 
                      (loc - settings["max_length"]//2))/location_scale)**2)
        p = softmax(T * weights)
      else:
        p = None

      idx_sample = np.random.choice(np.arange(n), 
                                    size= settings["sample_splits"],
                                    replace = False, p = p)
      prot_seq_trunc = [prot_seq_trunc[j] for j in idx_sample]
      aa_positions_ids = [aa_positions_ids[j] for j in idx_sample]

  return prot_seq_trunc, aa_positions_ids

# Custom Dataset
class Dataset(torch.utils.data.Dataset):

  def __init__(self, df, tokenizer = None, settings = None, debug = False):
    """
    - df: Dataframe with columns protein_sequence, pH, tm and sequence_id
    - tokenizer:  Set tokenizer
    - max_length: Fixed length of window to select from the sequence
    - truncate_option: Acceptable values in ["single", "all"]. "single" is for 
          selecting a random single window of length max_length. "split" is for 
          dividing the sequence to multiple windows of max_length (with overlap),
          and return a list of these windows.
    - overlap:  If truncate_optin is "all", overlp is the percentage of tokens 
          to overlap between each consecutive windows. 
    """
    self.df = df.reset_index(drop=True)
    if debug:
      self.df = self.df.sample(frac = 0.25)
    self.tokenizer = tokenizer
    # Set token_settings defaults
    if settings is None:
      self.settings = Dataset.settings_default
    self.settings = settings

  def __len__(self):
    return len(self.df)

  def __getitem__(self, i):

    prot = self.df.iloc[i]
    # Prepare output
    data = {
        "id": i,
        "pH": prot["pH"] 
    }
    if "tm" in prot.keys():
      data["tm"] = prot["tm"]

    # Initial number of splits
    n = 1
    
    # Truncate
    prot_seq = prot['protein_sequence']

    if ((self.settings["max_length"] is not None) and 
        (len(prot_seq) > self.settings["max_length"] - 2)):
      
      assert self.settings["truncate"] in ["single", "split"], "Wrong Option."

      # Get sub_locations for weighted sampling
      if isinstance(prot["sub_locations"], list):
        sub_locations = prot["sub_locations"]
      else:
        sub_locations = None

      # Truncate
      prot_seq_trunc, aa_position_ids = truncate_sequence(prot_seq, 
                                      self.settings, sub_locations)
 
      if self.tokenizer is None:
        data["protein_sequence"] = prot_seq_trunc
        return data

      # Prep and tokenize
      input_ids = []
      attention_mask = []
      position_ids = []

      for prot_wind, aa_pos_id in zip(prot_seq_trunc, aa_position_ids):
        # prot_seq of max_length -> max_length + 1 ([CLS])
        
        win_ids, win_mask = self.tokenizer(" ".join(prot_wind), 
                                    padding = 'max_length', 
                                    max_length = self.settings["max_length"] + 2,
                                    return_tensors = 'pt').values()
        
        win_ids, win_mask = win_ids.squeeze(), win_mask.squeeze()
        # win_ids max_length + 2

        # First window 
        if 0 in aa_pos_id:
          # Substitute X with [SEP] token at the beginning
          win_ids[1] = win_ids[-1]
          win_mask[1] = win_mask[-1]
          # Drop [SEP] at end -> max_length + 1
          win_ids = win_ids[:-1]
          win_mask = win_mask[:-1] 
          # Add o for [CLS] -> max_length + 1
          aa_pos_id = np.concatenate([[0] , aa_pos_id])

        # Last window
        elif (len(prot_seq) + 1 in aa_pos_id):
          # Remove X -> max_length + 1
          win_ids = torch.cat([win_ids[:-2], win_ids[-1:]])
          win_mask = torch.cat([win_mask[:-2], win_mask[-1:]])
          # Sub 0 for [SEP]
          aa_pos_id[-1] = 0
          # Add o for [CLS] -> max_length + 1
          aa_pos_id = np.concatenate([[0] , aa_pos_id,
                                      [0] * (self.settings["max_length"] 
                                             - len(aa_pos_id))])
        
        # Intermediate window
        else:
          # Remove the [SEP] token
          win_ids = win_ids[:-1]
          win_mask = win_mask[:-1] 
          # Add o for [CLS] -> max_length + 1
          aa_pos_id = np.concatenate([[0] , aa_pos_id])

        input_ids.append(win_ids)
        attention_mask.append(win_mask)
        position_ids.append(aa_pos_id)

      try:
        input_ids = torch.stack(input_ids)
        attention_mask = torch.stack(attention_mask)
        position_ids = torch.from_numpy(np.array(position_ids, dtype =int))
      except:
        print(f"Dimension error for protein: {i}.")

    elif self.tokenizer is None: 
        data["protein_sequence"] = prot_seq
        return data

    # If sequence shorter than max_length
    elif self.settings["max_length"] is not None:
      # Prep for tokenization
      input_ids, attention_mask = self.tokenizer(" ".join(prot_seq), 
                                padding = 'max_length', 
                                max_length = self.settings["max_length"] + 1,                                      
                                return_tensors = 'pt').values()

      position_ids = torch.arange(len(prot_seq) + 1, dtype = torch.int)
      position_ids = torch.cat([position_ids, 
                                torch.zeros(self.settings["max_length"] 
                                - len(prot_seq), dtype = torch.int)])
      position_ids = position_ids.unsqueeze(0)
      
    else:
      prot_seq = " ".join(prot_seq)
      input_ids, attention_mask = self.tokenizer(prot_seq,                                     
                                    return_tensors = 'pt').values()      

    # Return
    data = {"input_ids": input_ids, 
            "attention_mask": attention_mask,
            "pH": torch.tensor(prot['pH'], dtype = torch.float32), 
            "id": i,
            "len_protein_sequence": len(prot_seq)}

    # Add position ids
    if "position_ids" in locals():
      data["position_ids"] = position_ids
  
    # If training sets
    if "tm" in prot.keys():
      data["tm"] = torch.tensor(prot['tm'],dtype = torch.float32)
    
    return data

  def sequence_sampler(self, batch_size, shuffle = True):
    """
    Sample sequences to form batches of the same number of sequences.
    Used for the "split" truncation.
    """
    # Compute number of AA per protein
    prot_lengths =  self.df["protein_sequence"].apply(
        lambda prot_seq: get_number_AA(prot_seq, self.settings))
    
    # Shuffle 
    if shuffle:
      prot_lengths = prot_lengths.sample(frac=1).astype(int)
    # Groups consecutive batches according to batch size
    list_group_ids = []
    group_ids = []
    prot_len_group = 0
    for prot_id, prot_len in prot_lengths.iteritems():
      prot_len_group += prot_len
      group_ids.append(prot_id)
      if prot_len_group >= batch_size:
        list_group_ids.append(group_ids)
        group_ids = []
        prot_len_group = 0
    if len(group_ids) != 0:
      list_group_ids.append(group_ids)

    return list_group_ids

  def group_mutations(self, ids, tm_pred):
    """
    Takes the batch of samples and groups mutations in pairs for Pairwise loss
    """
    label_rank = []
    tm_pred_1 = []
    tm_pred_2 = []

    if len(ids) == 1:
      return None, None, None
    # Look for proteins with corresponding ids
    df_groups = self.df.loc[ids,["sub_group","tm"]].reset_index(drop = True)
    # Keep only groups  
    df_groups = df_groups[~df_groups["sub_group"].isna()]
    df_groups = df_groups[df_groups.duplicated("sub_group", keep = False)]
    
    idx_keep = df_groups.index
    if len(idx_keep) == 0:
      return None, None, None

    for idx_group, group in df_groups.groupby("sub_group"):

      # Compute all possible combinations of pairs
      idx_pairs_1, idx_pairs_2 = list(
          zip(*itertools.combinations(group.index,2)))
      
      # Get tm_pred
      tm_pred_1.append(torch.tensor([tm_pred[i] for i in idx_pairs_1]))
      tm_pred_2.append(torch.tensor([tm_pred[i] for i in idx_pairs_2]))
      # Get rank
      rank = (df_groups.loc[list(idx_pairs_1),"tm"].values - 
              df_groups.loc[list(idx_pairs_2),"tm"].values)

      if isinstance(rank, float):
        rank = np.sign(rank).reshape(len(idx_pairs_1),)
      else:
        rank = np.sign(rank)
      label_rank.append(rank)

    label_rank = torch.from_numpy(np.concatenate(label_rank)).float()
    tm_pred_1 = torch.cat(tm_pred_1).float()
    tm_pred_2 = torch.cat(tm_pred_2).float()

    return tm_pred_1, tm_pred_2, label_rank

  def compute_mutation_SCC(self, ids, tm_pred):
    """
    Evaluate Spearman's Correlation Coefficient with respect to mutations
    - tm_pred can be a torch tensor
    """
    # Join group
    df_pred = pd.DataFrame(data = tm_pred, index = ids, columns = ["tm_pred"])
    df_pred = df_pred.join(self.df[["sub_group","tm"]])
    # Get only groups 
    df_pred = df_pred[~df_pred["sub_group"].isna()]
    if len(df_pred) == 0:
      return None

    # Groupby and compute SCC
    s_SCC = df_pred.groupby("sub_group").apply(
        lambda g: g["tm"].corr(g["tm_pred"], method = "spearman"))

    return s_SCC

  @staticmethod
  def collate(batch):
    input_ids  = []
    attention_mask = []
    position_ids = []
    ph = []
    id = []
    n_splits = []
    try:
      if "tm" in batch[0].keys():
        tm = []

      for data in batch:
        
        input_ids.append(data["input_ids"])
        attention_mask.append(data["attention_mask"])
        ph.append(data["pH"])
        id.append(data["id"])
        n_splits.append(len(data["input_ids"]))

        if "tm" in data.keys():
          tm.append(data["tm"])
        
        if "position_ids" in data.keys():
          position_ids.append(data["position_ids"])

      # Stack all sequences from different prot
      input_ids = torch.cat(input_ids)
      attention_mask = torch.cat(attention_mask)
      position_ids = torch.cat(position_ids) 

      data = {"input_ids": input_ids,
              "attention_mask": attention_mask,
              "position_ids": position_ids,
              "pH": torch.stack(ph),
              "id": id,
              "n_splits": n_splits}

      if "tm" in batch[0].keys():
        data["tm"] = torch.stack(tm)
    except Exception as e:
      print("Error in protein ", id)
      print(e)
    
    return data 

  settings_default = {"max_length" : None, 
                    "truncate" : "single", 
                    "overlap" : 0, 
                    "sample_splits" : None}  

class DatasetPairs(torch.utils.data.Dataset):
                             
  def __init__(self, df_mutations, tokenizer = None, settings = None):
    
    self.df_mutations = df_mutations.copy(deep = True)

    # Join size of mutation group
    sub_group_counts = self.df_mutations.value_counts("sub_group") 
    sub_group_counts.rename("n_sub", inplace = True)
    self.df_mutations = self.df_mutations.join(sub_group_counts, on="sub_group")
    # check occurance of prot during training
    self.df_mutations["occurrence"] = 0
    self.tokenizer = tokenizer
    # Set token_settings defaults
    if settings is None:
      self.settings = DatasetPairs.settings_default
    self.settings = settings

  def __len__(self):
    return len(self.df_mutations)

  def __getitem__(self, i):

    # Get protein
    prot = self.df_mutations.loc[i]

    # Get corresponding pair  
    i_pair = self.dict_sampled[i][0]
    # Set as processed
    if len(self.dict_sampled[i]) > 1:
      self.dict_sampled[i] = self.dict_sampled[i][1:]
    else:
      self.dict_sampled[i] = []

    pair = self.df_pairs.loc[i_pair]

    # Get diff_locations
    diff_locations = pair["diff_locations"]

    # Number of splits
    n = 1

    # Truncate
    prot_seq = prot['protein_sequence']
    if ((self.settings["max_length"] is not None) and 
        (len(prot_seq) > self.settings["max_length"] - 2)):
      
      assert self.settings["truncate"] in ["single", "split"], "Wrong Option."

      # Truncate sequence
      prot_seq_trunc, aa_position_ids = truncate_sequence(prot_seq, 
                                              self.settings, diff_locations)

      if self.tokenizer is None:
        data["protein_sequence"] = prot_seq_trunc
        return data
      

      # Prep and tokenize
      input_ids = []
      attention_mask = []
      position_ids = []

      for prot_wind, aa_pos_id in zip(prot_seq_trunc, aa_position_ids):
        # prot_seq of max_length -> max_length + 1 ([CLS])
        win_ids, win_mask = self.tokenizer(" ".join(prot_wind), 
                                    padding = 'max_length', 
                                    max_length = self.settings["max_length"] + 2,
                                    return_tensors = 'pt').values()
        
        win_ids, win_mask = win_ids.squeeze(), win_mask.squeeze()
        # win_ids max_length + 2

        # First window 
        if 0 in aa_pos_id:
          # Substitute X with [SEP] token at the beginning
          win_ids[1] = win_ids[-1]
          win_mask[1] = win_mask[-1]
          # Drop [SEP] at end -> max_length + 1
          win_ids = win_ids[:-1]
          win_mask = win_mask[:-1] 
          # Add o for [CLS] -> max_length + 1
          aa_pos_id = np.concatenate([[0] , aa_pos_id])

        # Last window
        elif (len(prot_seq) + 1 in aa_pos_id):
          # Remove X -> max_length + 1
          win_ids = torch.cat([win_ids[:-2], win_ids[-1:]])
          win_mask = torch.cat([win_mask[:-2], win_mask[-1:]])
          # Sub 0 for [SEP]
          aa_pos_id[-1] = 0
          # Add o for [CLS] -> max_length + 1
          aa_pos_id = np.concatenate([[0] , aa_pos_id,
                                      [0] * (self.settings["max_length"] 
                                             - len(aa_pos_id))])
        
        # Intermediate window
        else:
          # Remove the [SEP] token
          win_ids = win_ids[:-1]
          win_mask = win_mask[:-1] 
          # Add o for [CLS] -> max_length + 1
          aa_pos_id = np.concatenate([[0] , aa_pos_id])

        input_ids.append(win_ids)
        attention_mask.append(win_mask)
        position_ids.append(aa_pos_id)

      try:
        input_ids = torch.stack(input_ids)
        attention_mask = torch.stack(attention_mask)
        position_ids = torch.from_numpy(np.array(position_ids, dtype =int))
      except:
        print(f"Dimension error for protein: {i}.")

    # No truncation no tokenizer
    elif self.tokenizer is None: 
        data["protein_sequence"] = prot_seq
        return data

    # If sequence shorter than max_length
    elif self.settings["max_length"] is not None:
      # Prep for tokenization
      input_ids, attention_mask = self.tokenizer(" ".join(prot_seq), 
                                padding = 'max_length', 
                                max_length = self.settings["max_length"] + 1,                                      
                                return_tensors = 'pt').values()

      position_ids = torch.arange(len(prot_seq) + 1, dtype = torch.int)
      position_ids = torch.cat([position_ids, 
                                torch.zeros(self.settings["max_length"] 
                                - len(prot_seq), dtype = torch.int)])
      position_ids = position_ids.unsqueeze(0)
      
    else:
      prot_seq = " ".join(prot_seq)
      input_ids, attention_mask = self.tokenizer(prot_seq,                                     
                                    return_tensors = 'pt').values()           
    # Return
    data = {"input_ids": input_ids, 
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "pH": torch.tensor(prot['pH'], dtype = torch.float32), 
            "id": i,
            "pair_id": pair.name}
    
    # If training sets
    if "tm" in prot.keys():
      data["tm"] = torch.tensor(prot['tm'],dtype = torch.float32)

    return data

  def pair_sampler(self, batch_size_min, n_batches_max = None, 
                   coverage_rate_min = None):

    assert (n_batches_max is not None) or (coverage_rate_min is not None), (
        "Assign either batch_size_min or coverage_rate.")
    
    if n_batches_max is None:
      n_batches_max = np.inf
    if coverage_rate_min is None:
      coverage_rate_min = np.inf

    # dict of pairs info
    dict_pairs = {}
  	# dict to check if sampled
    self.dict_sampled = {}

    i_batch = 0
    coverage_rate = 0
    i_pair = 0

    all_pairs = []
    for g_id, group in self.df_mutations.groupby("sub_group"):
      group_pairs = list(itertools.combinations(group.index.values, 2))
      all_pairs.append(group_pairs)
    all_pairs = np.concatenate(all_pairs)
    all_pairs = np.random.permutation(all_pairs)

    while i_batch <= n_batches_max and coverage_rate < coverage_rate_min:

      batch_size = 0

      while batch_size < batch_size_min:
        id_1, id_2 = all_pairs[i_pair]

        prot_1 = self.df_mutations.loc[id_1]
        prot_2 = self.df_mutations.loc[id_2]
          
        # Add pair to dict
        dict_pairs[(id_1, id_2)] = {"i_batch": i_batch,
                                    "diff_tm": prot_1["tm"] - prot_2["tm"],
                                    "sub_group": prot_1["sub_group"] }
        # Add pair to dict of sampled
        if id_1 not in self.dict_sampled.keys():
          self.dict_sampled[id_1] = [i_pair]
        else:
          self.dict_sampled[id_1].append(i_pair)
        # Same for second pair
        if id_2 not in self.dict_sampled.keys():
          self.dict_sampled[id_2] = [i_pair]
        else:
          self.dict_sampled[id_2].append(i_pair)       

        # Add occurances
        self.df_mutations.loc[id_1, "occurrence"] += 1
        self.df_mutations.loc[id_2, "occurrence"] += 1

        # Get sequences
        prot_seq_1 = prot_1["protein_sequence"]
        prot_seq_2 = prot_2["protein_sequence"]

        # Add batch_size
        n_AA = get_number_AA(prot_seq_1, self.settings)
        batch_size += 2 * n_AA 

        # Get position differences
        sub_locations = set()
        if isinstance(prot_1["sub_locations"], list):
          sub_locations.update(prot_1["sub_locations"])
        if isinstance(prot_2["sub_locations"], list):
          sub_locations.update(prot_2["sub_locations"])
        

        diff_locations = []
        for loc in sub_locations:
          if prot_seq_1[loc] != prot_seq_2[loc]:
            diff_locations.append(loc)

        dict_pairs[(id_1,id_2)]["diff_locations"] = diff_locations

        i_pair += 1

      i_batch += 1

    # Save dict in dataframe
    self.df_pairs = pd.DataFrame.from_dict(dict_pairs, orient = "index")
    self.df_pairs.reset_index(inplace =True)
    self.df_pairs.rename(columns = {"level_0": "id_1", "level_1": "id_2"}, 
                         inplace =True)
    # Print stats
    s_groups = self.df_mutations.loc[
        self.df_pairs["id_1"].tolist()].value_counts("n_sub")
    #print(f"\nLen of groups stats:\n{s_groups.sort_index()}")
    # Compute coverage rate
    coverage = set(self.df_pairs["id_1"].tolist() + 
                   self.df_pairs["id_2"].tolist())
    coverage_rate = np.isin(self.df_mutations.index.values,list(coverage)).sum()
    coverage_rate /= len(self.df_mutations)
    print(f"Coverage: {coverage_rate *100 : .1f}")
    # Occurrences stats
    #print(f"\nProtein occurence stats:\n"
    #      f"{self.df_mutations['occurrence'].describe()}")
    # Prepare sampling list
    list_batch_ids = []
    for i_batch, batch in self.df_pairs.groupby("i_batch"):
      list_batch_ids.append(batch["id_1"].tolist() + 
                            batch["id_2"].tolist())
    
    return list_batch_ids

  @staticmethod
  def collate(batch):
    input_ids  = []
    attention_mask = []
    position_ids = []
    ph = []
    id = []
    pair_id = []
    n_splits = []

    if "tm" in batch[0].keys():
      tm = []

    for data in batch:
      input_ids.append(data["input_ids"])
      attention_mask.append(data["attention_mask"])
      ph.append(data["pH"])
      id.append(data["id"])
      pair_id.append(data["pair_id"])
      n_splits.append(len(data["input_ids"]))

      if "tm" in data.keys():
        tm.append(data["tm"])

      if "position_ids" in data.keys():
        position_ids.append(data["position_ids"])
    
    # Stack all sequences from different prot
    input_ids = torch.cat(input_ids)
    attention_mask = torch.cat(attention_mask)
    position_ids = torch.cat(position_ids) 

    data = {"input_ids": input_ids,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            "pH": torch.stack(ph),
            "id": id,
            "pair_id": pair_id,
            "n_splits": n_splits}

    if "tm" in batch[0].keys():
      data["tm"] = torch.stack(tm)
    
    return data 

  settings_default = {"max_length" : None, 
                      "truncate" : "single", 
                      "overlap" : 0, 
                      "sample_splits" : None}