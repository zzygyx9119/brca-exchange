#!/usr/bin/env python
"""
this scripts takes the enigma variant list and merge vcf files in a folder into
the exisitng enigma variants:
"""
import argparse
import datetime
import os
import pickle
import re
import shutil
import subprocess
import tempfile
import vcf
from StringIO import StringIO
from copy import deepcopy
from pprint import pprint


#GENOMIC VERSION:
VERSION = "hg38" # equivalent to GRCh38

# Specific columns in the output matrix
COLUMN_SOURCE = 0
COLUMN_GENE = 1
COLUMN_GENOMIC_HGVS = 2
COLUMN_VCF_CHR = 3
COLUMN_VCF_POS = 4
COLUMN_VCF_REF = 5
COLUMN_VCF_ALT = 6

# This is the string to be stored when a field is empty
DEFAULT_CONTENTS = "-"

# files needed for string comparison

#key value pair dictionaries of all extra fields in various databases to add
GENOME1K_FIELDS = {"Allele_frequency":"AF",
                   "EAS_Allele_frequency":"EAS_AF",
                   "EUR_Allele_frequency":"EUR_AF",
                   "AFR_Allele_frequency":"AFR_AF",
                   "AMR_Allele_frequency":"AMR_AF",
                   "SAS_Allele_frequency":"SAS_AF"}
CLINVAR_FIELDS = {"HGVS": "HGVS",
                  "Submitter":"Submitter",
                  "Clinical_Significance":"ClinicalSignificance",
                  "Date_Last_Updated":"DateLastUpdated",
                  "SCV":"SCV",
                  "Allele_Origin":"Origin",
                  "Protein":"Protein",
                  "Method":"Method"}
LOVD_FIELDS = {"Origin_of_variant": "genetic_origin",
               "Variant_frequency": "frequency",
               "Variant_haplotype": "haplotype",
               "Functional_analysis_result": "functionalanalysis_result",
               "Functional_analysis_technique": "functionalanalysis_technique",
               "dna_change_genomic": "dna_change_genomic",
               "HGVS_cDNA": "dna_change",
               "HGVS_protein": "protein_change"}
EX_LOVD_FIELDS = {"Combined_prior_probablility": "combined_prior_p",
                  "Segregation_LR": "segregation_lr",
                  "Sum_family_LR": "sum_family_lr",
                  "Co_occurrence_LR": "co_occurrence_lr",
                  "Missense_analysis_prior_probability": "missense_analysis_prior_p",
                  "Posterior_probability": "posterior_p",
                  "IARC_class":"iarc_class",
                  "BIC_Nomenclature": "bic_dna_change",
                  "Literature_source":"observational_reference",
                  "HGVS_cDNA": "dna_change",
                  "HGVS_protein": "protein_change"}
BIC_FIELDS = {"Clinical_classification": "Category",
              "Number_of_family_member_carrying_mutation": "Number_Reported",
              "Patient_nationality": "Nationality",
              "Germline_or_Somatic": "G_or_S",
              "Mutation_type": "Mutation_Type",
              "BIC_Designation": "Designation",
              "Clinical_importance": "Clinically_Importance",
              "Ethnicity": "Ethnicity",
              "Literature_citation": "Reference"}
ESP_FIELDS = {"polyPhen2_result": "PH",
              "Minor_allele_frequency":"MAF"}
EXAC_FIELDS = {"Allele_frequency": "AF"}

FIELD_DICT = {"1000_Genomes": GENOME1K_FIELDS,
               "ClinVar": CLINVAR_FIELDS,
               "LOVD": LOVD_FIELDS,
               "exLOVD": EX_LOVD_FIELDS,
               "ExAC": EXAC_FIELDS,
               "ESP": ESP_FIELDS,
               "BIC": BIC_FIELDS}

ENIGMA_FILE = "ENIGMA_last_updated_05-21-2016.tsv"
GENOME1K_FILE = "1000G_brca.sorted.hg38.vcf"
CLINVAR_FILE = "ClinVarBrca.vcf"
LOVD_FILE = "sharedLOVD_brca12.sorted.hg38.vcf"
EX_LOVD_FILE = "exLOVD_brca12.sorted.hg38.vcf"
BIC_FILE = "bic_brca12.sorted.hg38.vcf"
EXAC_FILE = "exac.brca12.sorted.hg38.vcf"
ESP_FILE = "esp.brca12.sorted.hg38.vcf"


parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", help="Input VCF directory",
                    default="/home/brca/pipeline-data/pipeline-input/")
parser.add_argument("-o", "--output", 
                    default="/home/brca/pipeline-data/pipeline-output/")
parser.add_argument("-p", "--de_novo", default=False,
                    help="string comparison all over, instead of loading from pickle dump",
                    action="store_true")
parser.add_argument('-r', "--reference", help="reference data directory",
                    default="/home/brca/pipeline-data/pipeline-resources/")
ARGS = parser.parse_args()


BRCA1 = {"hg38": {"start": 43000000,
                  "sequence": open(ARGS.reference + "brca1_hg38.txt", "r").read()},
         "hg19": {"start": 41100000,
                  "sequence": open(ARGS.reference + "brca1_hg19.txt", "r").read()}}
BRCA2 = {"hg38": {"start": 32300000,
                  "sequence": open(ARGS.reference + "brca2_hg38.txt", "r").read()},
         "hg19": {"start": 32800000,
                  "sequence": open(ARGS.reference + "brca2_hg19.txt", "r").read()}}
  
def main():
    tmp_dir = tempfile.mkdtemp()
    try:
        source_dict, columns, variants = preprocessing(tmp_dir)
        print "\n------------merging different dataset------------------------------"
        for source_name, file in source_dict.iteritems():
            (columns, variants) = add_new_source(columns, variants, source_name, 
                                                 file, FIELD_DICT[source_name])
        print "------------string comparison merge-------------------------------"
        variants = variant_standardize(variants=variants)
        variants = string_comparison_merge(variants) 
        write_new_tsv(ARGS.output + "merged.tsv", columns, variants)
        print "final number of variants: %d" %len(variants)
        print "Done" 
    finally:
        shutil.rmtree(tmp_dir)


def variant_standardize(variants="pickle"): 
    """standardize variants such 
    1. "-" in ref or alt is removed, and a leading base is added, e.g. ->T is changed to N > NT
    2. remove trailing same bases: e.g. AGGGG > TGGGG is changed to A>T
    3. remove leading same baes: e.g. position 100, AAT > AAG is changed to position 102 T>G
    """
    if variants=="pickle":
        with open("temp_variants.pkl", "r") as fv:
            variants = pickle.loads(fv.read())
        fv.close()
    variants_to_remove = list()
    variants_to_add = {}
    for ev, items in variants.iteritems():
        chr = items[COLUMN_VCF_CHR]
        pos = items[COLUMN_VCF_POS]
        ref = items[COLUMN_VCF_REF]
        alt = items[COLUMN_VCF_ALT]
        if ref == "None":
            ref = ""
        if alt == "None":
            alt = ""
        if re.search("^-", ref) or re.search("^-", alt):
            (chr, pos, ref, alt) = add_leading_base(chr, pos, ref, alt)
        if len(ref) < 1 or len(alt) < 1:
            (chr, pos, ref, alt) = add_leading_base(chr, pos, ref, alt)
        (chr, pos, ref, alt) = trim_bases(chr, pos, ref, alt)
        #if type(items[2]) == list:
        #    variant_names = items[2]
        #else:
        #    variant_names = [items[2]]
        #new_names = []
        #for vv in variant_names:
        #    if ("-" in vv) or refOrAltMissing(vv):
        #        vv2 = add_leading_base(vv)
        #    else:
        #        vv2 = vv
        #    if not re.search("None", vv2):
        #        new_names.append(trim_bases(vv2))
        #    else:
        #        new_names.append(vv2)
        #                        
        #new_names = [add_leading_base(v) if ("-" in v) or refOrAltMissing(v)  else v for v in variant_names]
        #new_names = [trim_bases(v) if "None" not in v else v for v in new_names]
        #new_names = ",".join(list(set(new_names)))
        items[COLUMN_VCF_POS] = pos
        items[COLUMN_VCF_REF] = ref
        items[COLUMN_VCF_ALT] = alt
        newHgvs = "chr%s:%s:%s>%s" % (str(chr), str(pos), ref, str(alt))
        if newHgvs != ev:
            variants_to_remove.append(ev)
            variants_to_add[newHgvs] = items
    for old_variant in variants_to_remove:
        variants.pop(old_variant)
    for key, values in variants_to_add.iteritems():
        variants[key] = values
    return variants

def refOrAltMissing(v):
    ref, alt = v.split(":")[2].split(">")
    if len(ref) < 1 or len(alt) < 1:
        return True
    else:
        return False

def trim_bases(chr, pos, ref, alt):
    #ref, alt = v.split(":")[2].split(">")
    if len(ref) <= 1 or len(alt) <= 1:
        return (chr, pos, ref, alt)
    else:
        (ref, alt) = trim_trailing(ref, alt)
        #v = ":".join(v.split(":")[0:2] + ["{0}>{1}".format(ref, alt)])
        (chr, pos, ref, alt) = trim_leading(chr, pos, ref, alt)
        return (chr, pos, ref, alt)

def trim_trailing(ref, alt):
    if len(ref) <= 1 or len(alt) <= 1: 
        return ref, alt    
    elif ref[-1] != alt[-1]:
        return ref, alt    
    else:
        ref = ref[:-1]
        alt = alt[:-1]
        return trim_trailing(ref, alt)

def trim_leading(chr, pos, ref, alt):
    #chr, pos, refalt = v.replace("-", "").split(":")
    pos = int(pos)
    #ref, alt = refalt.split(">")
    if len(ref) == 1 or len(alt) == 1 or ref[0] != alt[0]:
        return (chr, pos, ref, alt)
    else:
        ref = ref[1:]
        alt = alt[1:]
        pos += 1
        #new_v = "{0}:{1}:{2}>{3}".format(chr, str(pos), ref, alt)
        return trim_leading(chr, str(pos+1), ref, alt)


def add_leading_base(chr, pos, ref, alt, version="hg38"):
    #chr, pos, refalt = v.replace("-", "").split(":")
    pos = int(pos)
    #ref, alt = refalt.split(">")
    if ref == "-":
        ref = ""
    if alt == "-":
        alt = ""
    if chr == "13":
        seq = BRCA2[version]["sequence"]
        brca_pos = pos - 1 - BRCA2[version]["start"]
    elif chr == "17":
        seq = BRCA1[version]["sequence"]
        brca_pos = pos - 1 - BRCA1[version]["start"]
    else:
        raise Exception("wrong chromosome number")
    # correct error with when ref is empty string
    if len(ref) == 0:
        brca_pos += 1
    else:
        assert(seq[brca_pos:brca_pos + len(ref)] == ref)
    leading_base = seq[brca_pos-1]
    new_v = "{0}:{1}:{2}>{3}".format(chr, str(pos-1), 
                                     leading_base + ref, leading_base + alt)
    return (chr, str(pos-1), leading_base + ref, leading_base + alt) 
    

def string_comparison_merge(variants):
    # make sure the input genomic coordinate strings are already unique strings
    assert (len(variants.keys()) == len(set(variants.keys())))
    if ARGS.de_novo:
        equivalence = find_equivalent_variant(variants)
        with open(ARGS.output + "equivalent_variants.pkl", "w") as f:
            f.write(pickle.dumps(equivalence))
        f.close()
    else:
        equivalence = pickle.loads(open(ARGS.output + "equivalent_variants.pkl", "r").read())
    n_before_merge = 0
    for each in equivalence:
        n_before_merge += len(each)
    n_after_merge = len(equivalence)
    print "%d equivalent variants are merged into %d unique variants" %(
          n_before_merge, n_after_merge)
    for equivalent_v in equivalence:
        # 
        # equivalent_v contains a set of variants found to be equivalent.
        # The next step is to merge data for these variants, which will
        # end up in the array merged_row.
        merged_row = []
        for each_v in equivalent_v:
            if len(merged_row) == 0:
                #
                # If this is the first variant in the equivalence set, initialize
                # the merged data to the data for this variant.
                merged_row = variants[each_v]
            else:
                for index, values_merged_so_far in enumerate(merged_row):
                    values_to_be_merged = variants[each_v][index]
                    # If either the new value or the old value is non-blank, use it.
                    if values_merged_so_far == DEFAULT_CONTENTS and values_to_be_merged != DEFAULT_CONTENTS:
                        merged_row[index] = values_to_be_merged
                    elif values_merged_so_far != DEFAULT_CONTENTS and values_to_be_merged == DEFAULT_CONTENTS:
                        merged_row[index] = values_merged_so_far
                        # Skip over the VCF columns.  We're going to assume that one
                        # equivalence of them is enough, which will simplify life for
                        # downstream methods.
                    elif index == COLUMN_VCF_CHR or index == COLUMN_VCF_POS or index == COLUMN_VCF_REF or index == COLUMN_VCF_ALT:
                        continue
                    else:
                        # If both the new value and old value are non-blank and different,
                        # generate a list that contains both new and old values.
                        # If the old value is already a list, append the new value.
                        # If the old value is not a list, create a list containing the old
                        # value and append the new value.  
                        if values_merged_so_far != values_to_be_merged:
                            if type(values_merged_so_far) != list:
                                values_merged_so_far = [values_merged_so_far]
                            if values_to_be_merged not in values_merged_so_far:
                                if type(values_to_be_merged) == list:
                                    values_merged_so_far.extend(values_to_be_merged)
                                else:
                                    values_merged_so_far.append(values_to_be_merged)
                            merged_row[index] = values_merged_so_far
            #
            # Remove each variant in the equivalence set from the hash of 
            # variants.  Later on, we'll add an entry for the entire equivalence 
            # set.
            variants.pop(each_v)
        variants[",".join(list(equivalent_v))] = merged_row
    return variants

def find_equivalent_variant(variants):
    genome_coors = variants.keys()
    uniq_variants = {}
    for i, v in enumerate(genome_coors):
        variant_exist = False
        for existing_v in uniq_variants:
            if v == existing_v:
                continue
            else:
                v1 = [variants[v][COLUMN_VCF_CHR], variants[v][COLUMN_VCF_POS], variants[v][COLUMN_VCF_REF], variants[v][COLUMN_VCF_ALT]]
                v2 = [variants[existing_v][COLUMN_VCF_CHR], variants[existing_v][COLUMN_VCF_POS], variants[existing_v][COLUMN_VCF_REF], variants[existing_v][COLUMN_VCF_ALT]]
                if variant_equal(v1, v2):
                #v1 = v.replace("-", "").replace("chr", "").replace(">", ":")
                #v2 = existing_v.replace("-", "").replace("chr", "").replace(">", ":")
                #if variant_equal(v1.split(":"), v2.split(":")):
                    variant_exist = True
                    uniq_variants[existing_v].add(v)
        if not variant_exist:
            uniq_variants[v] = set([v])
    equivalent_variants = [] 
    for value in uniq_variants.values():
        if len(value) > 1:
            equivalent_variants.append(value)
    return equivalent_variants

def preprocessing(tmp_dir):
    # Preprocessing variants:
    source_dict = {"1000_Genomes": GENOME1K_FILE + "for_pipeline",
                   "ClinVar": CLINVAR_FILE,
                   "LOVD": LOVD_FILE,
                   "exLOVD": EX_LOVD_FILE,
                   "ExAC": EXAC_FILE,
                   "ESP": ESP_FILE,
                   "BIC": BIC_FILE,
                   }    
    print "\n" + ARGS.input + ":"
    print "---------------------------------------------------------"
    print "ENIGMA: {0}".format(ENIGMA_FILE)
    for source_name, file_name in source_dict.iteritems():
        print source_name, ":", file_name
    print "\n------------preprocessing--------------------------------"
    print "remove sample columns and two erroneous rows from 1000 Genome file"
    f_1000G = open(ARGS.input + GENOME1K_FILE + "for_pipeline", "w")
    subprocess.call(
       ["bash", "1000g_preprocess.sh", ARGS.input + GENOME1K_FILE], stdout=f_1000G)
   
    # merge multiple variant per vcf into multiple lines 
    for source_name, file_name in source_dict.iteritems():
        print "convert to one variant per line in ", source_name
        f_in = open(ARGS.input + file_name, "r")
        f_out = open(tmp_dir + "/" + source_name + ".vcf", "w")
        one_variant_transform(f_in, f_out)
        f_in.close()
        f_out.close()
        print "merge repetitive variants within ", source_name
        f_in = open(tmp_dir + "/" + source_name + ".vcf", "r")
        f_out = open(tmp_dir + "/" + source_name + "ready.vcf", "w")
        repeat_merging(f_in, f_out)
        source_dict[source_name] = f_out.name 
    
    print "-------check if genomic coordinates are correct----------"
    (columns, variants) = save_enigma_to_dict(ARGS.input + ENIGMA_FILE)
    for source_name, file_name in source_dict.iteritems():
        f = open(file_name, "r")
        d_wrong = ARGS.output + "wrong_genome_coors/"
        if not os.path.exists(d_wrong):
            os.makedirs(d_wrong)
        f_wrong = open(ARGS.output + "wrong_genome_coors/" + 
                       source_name + "_wrong_genome_coor.vcf", "w")
        f_right = open(tmp_dir + "/right" + source_name, "w")
        vcf_reader = vcf.Reader(f, strict_whitespace=True)
        vcf_wrong_writer = vcf.Writer(f_wrong, vcf_reader)
        vcf_right_writer = vcf.Writer(f_right, vcf_reader)
        n_wrong, n_total = 0, 0
        for record in vcf_reader:
            ref = record.REF.replace("-", "")
            v = [record.CHROM, record.POS, ref, "dummy"]
            if not ref_correct(record.CHROM, record.POS, record.REF, record.ALT):
                vcf_wrong_writer.write_record(record)
                n_wrong += 1
            else:
                vcf_right_writer.write_record(record)
            n_total += 1
        f_right.close()
        f_wrong.close()
        print "in {0}, wrong: {1}, total: {2}".format(source_name, n_wrong, n_total) 
    
    return source_dict, columns, variants

def repeat_merging(f_in, f_out):
    """takes a vcf file, collapses repetitive variant rows and write out
        to a new vcf file (without header)"""
    vcf_reader = vcf.Reader(f_in, strict_whitespace=True)
    variant_dict = {}
    num_repeats = 0
    for record in vcf_reader:
        genome_coor = "chr{0}:{1}:{2}>{3}".format(
            record.CHROM, str(record.POS), record.REF, record.ALT[0])
        if genome_coor not in variant_dict.keys():
            variant_dict[genome_coor] = deepcopy(record)
        else:
            num_repeats += 1
            for key in record.INFO:        
                if key not in variant_dict[genome_coor].INFO.keys():
                    variant_dict[genome_coor].INFO[key] = deepcopy(record.INFO[key])
                else:
                    new_value = deepcopy(record.INFO[key])
                    old_value = deepcopy(variant_dict[genome_coor].INFO[key])

                    if type(new_value) != list:
                        new_value = [new_value]
                    if type(old_value) != list:
                        old_value = [old_value]
                    if new_value  == old_value:
                        continue
                    else:
                        merged_value = list(set(new_value + old_value))
                        variant_dict[genome_coor].INFO[key] = deepcopy(merged_value)
    print "number of repeat records: ", num_repeats, "\n"
    vcf_writer = vcf.Writer(f_out, vcf_reader)
    for record in variant_dict.values():
        vcf_writer.write_record(record)
    f_in.close()
    f_out.close()

def get_header(f):
    header = ""
    for line in f:
        if "#" in line:
            header += line
    return header
    
def one_variant_transform(f_in, f_out):
    """takes a vcf file, read each row, if the ALT field contains more than 
       one item, create multiple variant row based on that row, writes new vcf"""
    vcf_reader = vcf.Reader(f_in, strict_whitespace=True)
    vcf_writer = vcf.Writer(f_out, vcf_reader)
    for record in vcf_reader:
        n = len(record.ALT)
        if n == 1:
            vcf_writer.write_record(record)
        else:
            for i in range(n):
                new_record = deepcopy(record)
                new_record.ALT = [deepcopy(record.ALT[i])]
                for key in record.INFO.keys():
                    value = deepcopy(record.INFO[key])
                    if type(value) == list and len(value) == n:
                        new_record.INFO[key] = [value[i]]
                vcf_writer.write_record(new_record)

def write_new_tsv(filename, columns, variants):
    merged_file = open(filename, "w")
    merged_file.write("\t".join(columns)+"\n")
    for key, variant in sorted(variants.iteritems()):
        if len(variant) != len(columns):
            raise Exception("mismatching number of columns in head and row")
        for ii in range(len(variant)):
            if type(variant[ii]) == list:
                comma_delimited_string = ",".join(str(xx) for xx in variant[ii])
                variant[ii] = comma_delimited_string
            elif type(variant[ii]) == int:
                variant[ii] = str(variant[ii])
        merged_file.write("\t".join(variant)+"\n")
    merged_file.close()


def add_new_source(columns, variants, source, source_file, source_dict):
    print "adding {0} into merged file.....".format(source)
    old_column_num = len(columns)
    for column_title in source_dict.keys():
        columns.append(column_title+"_{0}".format(source))
    vcf_reader = vcf.Reader(open(source_file, 'r'), strict_whitespace=True)
    overlap = 0
    variants_num = 0
    for record in vcf_reader:
        variants_num += 1
        genome_coor = ("chr" + str(record.CHROM) + ":g." + str(record.POS) + ":" +
                       record.REF + ">" + str(record.ALT[0]))
        if genome_coor in variants.keys():
            overlap += 1
            if type(variants[genome_coor][COLUMN_SOURCE]) != list:
                variants[genome_coor][COLUMN_SOURCE] = [variants[genome_coor][COLUMN_SOURCE]]
            variants[genome_coor][COLUMN_SOURCE].append(source)
        else: 
            variants[genome_coor] = ['-'] * old_column_num
            variants[genome_coor][COLUMN_SOURCE] = source
            chrm = genome_coor.split(":")[0]
            if record.CHROM == "13":
                variants[genome_coor][COLUMN_GENE] = "BRCA2"
            elif record.CHROM == "17":
                variants[genome_coor][COLUMN_GENE] = "BRCA1"
            else:
                raise Exception("Wrong chromosome")
            variants[genome_coor][COLUMN_GENOMIC_HGVS] = genome_coor
            variants[genome_coor][COLUMN_VCF_CHR] = record.CHROM
            variants[genome_coor][COLUMN_VCF_POS] = record.POS
            variants[genome_coor][COLUMN_VCF_REF] = record.REF
            variants[genome_coor][COLUMN_VCF_ALT] = str(record.ALT[0])
        for value in source_dict.values():
            try:
                variants[genome_coor].append(record.INFO[value])
            except KeyError:
                if source == "BIC":
                    variants[genome_coor].append(DEFAULT_CONTENTS)
                else:
                    raise Exception("uncaught weirdness")
    # for those enigma record that doesn't have a hit with new genome coordinate
    # add extra cells of "-" to the end of old record
    for value in variants.values():
        if len(value) != len(columns):
            value += [DEFAULT_CONTENTS] * len(source_dict)
    print "number of variants in " + source + " is ", variants_num
    print "overlap with previous dataset: ", overlap
    print "number of total variants with the addition of " + source + " is: ", len(variants), "\n"
    for index,value in variants.iteritems():
        if len(value) != len(columns):
            raise Exception("mismatching number of columns in head and row")
    return (columns, variants)


def save_enigma_to_dict(path):
    enigma_file = open(path, "r")
    variants = dict()
    columns = ""
    line_num = 0
    f_wrong = open(ARGS.output + "ENIGMA_wrong_genome.txt", "w")
    n_wrong, n_total = 0, 0
    for line in enigma_file:
        line_num += 1
        if line_num == 1:
            columns = line.strip().split("\t")
            columns = [c + "_ENIGMA" for c in columns if c != "Genomic_Coordinate"]
            columns.insert(COLUMN_SOURCE, "Source")
            columns.insert(COLUMN_GENOMIC_HGVS, "Genomic_Coordinate")
            columns.insert(COLUMN_VCF_CHR, "Chr")
            columns.insert(COLUMN_VCF_POS, "Pos")
            columns.insert(COLUMN_VCF_REF, "Ref")
            columns.insert(COLUMN_VCF_ALT, "Alt")
            f_wrong.write(line)
        else:
            items = line.strip().split("\t")
            items.insert(COLUMN_SOURCE, "ENIGMA")
            v = items[COLUMN_GENOMIC_HGVS].replace("-", "").replace("chr", "").replace(">", ":")
            (chrom, pos, ref, alt) = v.split(":")
            items.insert(COLUMN_VCF_CHR, chrom)
            items.insert(COLUMN_VCF_POS, pos)
            items.insert(COLUMN_VCF_REF, ref)
            items.insert(COLUMN_VCF_ALT, alt)
            for ii in range(len(items)):
                if items[ii] == None:
                    items[ii] = DEFAULT_CONTENTS 
            if ref_correct(chrom, pos, ref, alt):
                hgvs = "chr%s:g.%s:%s>%s" % (str(chrom), str(pos), ref, alt)
                variants[hgvs] = items
            else:
                n_wrong += 1
                f_wrong.write(line)
            n_total += 1
    f_wrong.close()
    print "in ENIGMA, wrong: {0}, total: {1}".format(n_wrong, n_total)
    return (columns, variants)


def variant_equal(v1, v2, version="hg38"):
    " return (edited1, edited2) "
    if v1 == v2:
        return True
    chr1, pos1, ref1, alt1 = v1
    chr2, pos2, ref2, alt2 = v2
    pos1 = int(pos1)
    pos2 = int(pos2)
    if chr1 != chr2:
        return False
    if (len(ref1) - len(alt1)) != (len(ref2) - len(alt2)):
        return False
    #    
    # if len(ref2)>100 or len(ref1)>100:
    #     return False
    # make sure that v1 is upstream of v2
    if pos1 > pos2:
        return variant_equal(v2, v1)
    #
    # lift coordinates and make everything 0-based
    if chr1 == "13":
        seq = BRCA2[version]["sequence"]
        pos1 = pos1 - 1 - BRCA2[version]["start"]
        pos2 = pos2 - 1 - BRCA2[version]["start"]
    elif chr1 == "17":
        seq = BRCA1[version]["sequence"]
        pos1 = pos1 - 1 - BRCA1[version]["start"]
        pos2 = pos2 - 1 - BRCA1[version]["start"]
    else:
        assert(False)
    #
    # correct error with when ref is empty string
    if len(ref1) == 0:
        pos1 += 1
    if len(ref2) == 0:
        pos2 += 1
    #
    # replace vcf ref string with alt string
    edited_v1 = seq[0:pos1]+alt1+seq[pos1+len(ref1):]
    edited_v2 = seq[0:pos2]+alt2+seq[pos2+len(ref2):]
    #
    return edited_v1 == edited_v2

def ref_correct(chr, pos, ref, alt, version="hg38"): 
    if  pos == "None":
        return False
    pos = int(pos) 
    if chr == "13": 
        seq = BRCA2[version]["sequence"] 
        pos = pos - 1 - BRCA2[version]["start"]
    elif chr == "17":
        seq = BRCA1[version]["sequence"]
        pos = pos - 1 - BRCA1[version]["start"]
    else:
        assert(False)
    genomeRef = seq[pos:pos+len(ref)].upper()
    if len(ref) != 0 and len(genomeRef)==0:
        print "%s:%s:%s>%s" % (chr, pos, ref, alt)
        raise Exception("ref not inside BRCA1 or BRCA2")
    if (genomeRef != ref):
        return False
    else:
        return True


if __name__ == "__main__":
    #print "hello world"
    main()

