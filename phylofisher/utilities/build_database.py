#!/usr/bin/env python
import csv
import os
import random
import string
import subprocess
import shutil
import sys
import textwrap
from glob import glob
from collections import defaultdict, Counter
import pandas as pd
from Bio import SeqIO
import re

from phylofisher import help_formatter


def rename_taxa():
    """"""

    # Read in to_rename.tsv
    rename_dict = dict()
    with open(args.rename, 'r') as infile:
        infile.readline()
        for line in infile:
            line = line.strip()
            line_list = line.split('\t')
            rename_dict[line_list[0]] = line_list[1:]

    # Rename in orthologs/ and paralogs/
    files = glob('orthologs/*.fas') + glob('paralogs/*.fas')
    for file in files:
        with open(file, 'r') as infile, open('tmp', 'w') as tmp_file:
            for line in infile:
                line = line.strip()
                for key, value in rename_dict.items():
                    if key in line:
                        line = line.replace(key, value[0])
                tmp_file.write(f'{line}\n')
        shutil.move('tmp', file)

    df = pd.read_csv('metadata.tsv', sep='\t')
    for key, value in rename_dict.items():
        df.loc[df['Unique ID'] == key, 'Long Name'] = value[1]
        df.loc[df['Unique ID'] == key, 'Unique ID'] = value[0]
    
    df.to_csv('metadata.tsv', sep='\t', index=False)


def get_ortho_taxa():
    """
    Returns unique set of taxa in orthologs dir
    """
    unique_orgs_orthos = set()
    files = glob('orthologs/*.fas')
    for file in files:
        with open(file, 'r') as infile:
            records = SeqIO.parse(infile, 'fasta')
            for record in records:
                unique_orgs_orthos.add(record.name)

    return unique_orgs_orthos


def get_meta_taxa():
    """
    Returns unique set of taxa in metadata
    """
    unique_orgs_meta = set()
    with open('metadata.tsv', 'r') as csvfile:
        reader = csv.reader(csvfile, delimiter='\t')
        for row in reader:
            if row[0] == 'Unique ID':
                continue
            unique_orgs_meta.add(row[0])
    return unique_orgs_meta


def check_taxa():
    """
    Checks to see if all taxa in metadata is in ortholog dir and vice-versa. If there are differences the script exits
    here and prints the discrepancies. Also replaces @'s and ..'s with _'s if present in the UniqueID

    :return: None
    """
    unique_orgs_orthos = get_ortho_taxa()
    unique_orgs_meta = get_meta_taxa()

    # Exits if there are differences and prints those differences
    if len(unique_orgs_meta - unique_orgs_orthos) > 0 or len(unique_orgs_orthos - unique_orgs_meta) > 0:
        if len(unique_orgs_meta - unique_orgs_orthos) > 0:
            print(f'Taxa in metadata but not in orthologs dir:')
            for org in (unique_orgs_meta - unique_orgs_orthos):
                print(org)
        if len(unique_orgs_orthos - unique_orgs_meta) > 0:
            print(f'Taxa in orthlog dir but not in metadata:')
            for org in (unique_orgs_orthos - unique_orgs_meta):
                print(org)
        sys.exit()


def id_generator(size=5, chars=string.digits):
    """
    Generate random number with 5 digits.
    :param size:
    :param chars:
    :return:
    """
    return ''.join(random.choice(chars) for _ in range(size))


def paralog_name(abbrev, keys):
    """"Prepare paralog name (short name + 5 random digits).
    Recursive function.
    example: Homosap..12345
    input: short name of an organism, names of already existing paralogs
    for a given organism
    return: unique paralog name"""
    id_ = id_generator()
    pname = f'{abbrev}..p{id_}'
    if pname not in keys:
        return pname
    else:
        paralog_name(abbrev, keys)


def prepare_diamond_input():
    """
    Prepares seqs for diamond in a way that it connects
    information about gene before sequence name.
    Example: Allomacr from ADK2.fas will be named
    ADK2@Allomacr at the for_diamond.fasta file.

    :return: None
    """
    files = glob('orthologs/*.fas')
    with open("for_diamond.fasta", 'w') as res:
        for file in files:
            gene = file.split('/')[-1].split('.')[0]
            for record in SeqIO.parse(file, 'fasta'):
                res.write(f'>{gene}@{record.name}\n{record.seq}\n')


def diamond():
    """
    Uses for_diamond.fasta to diamond orthomcl.diamonddb

    :return: None
    """
    with open('for_diamond.fasta', 'r') as infile, open('new.fas', 'w') as outfile:
        for line in infile:
            line = line.strip()
            if line.startswith(">") is False:
                line = line.replace('-', '')
            outfile.write(f'{line}\n')

    shutil.move('new.fas', 'for_diamond.fasta')

    db = 'orthomcl/orthomcl.diamonddb.dmnd'
    out = 'diamond.res'
    cmd = (
        f'diamond blastp -e 1e-10 -q for_diamond.fasta --more-sensitive '
        f'--db {db} -o {out} -p {args.threads} --outfmt 6 qseqid stitle evalue')
    subprocess.run(cmd, shell=True)


def parse_diamond_output():
    gene_ogs = defaultdict(list)
    for line in open('diamond.res'):
        sline = line.split("\t")
        full_name = sline[0]  # ADK2@Allomacr
        gene, _ = full_name.split('@')  # gene: ADK2
        og = sline[1].split('|')[2].strip()  # parse og name OG5_128398
        gene_ogs[gene].append(og)  # gene_ogs['ADK2'].append(og)
    return gene_ogs


def get_og_file(threshold):
    prepare_diamond_input()  # prepares orthologs for diamondF
    diamond()  # starts diamond
    gene_filtered_ogs = defaultdict(list)
    gene_ogs = parse_diamond_output()
    for gene, ogs in gene_ogs.items():
        total = len(ogs)
        counted = dict(Counter(ogs))
        for og, count in counted.items():
            if count / total >= threshold:
                gene_filtered_ogs[gene].append(og)
    with open('orthomcl/gene_og', 'w') as res:
        for gene, ogs in gene_filtered_ogs.items():
            res.write(f'{gene}\t{",".join(ogs)}\n')
    os.remove('diamond.res')
    os.remove('for_diamond.fasta')


def concat_gene_files():
    files = glob('*.fas')

    with open('datasetdb.fasta', 'w') as outfile:
        for file in files:
            with open(file, 'r') as infile:
                for line in infile:
                    line = line.strip()
                    if line.startswith('>'):
                        line = f'>{file.split(".")[0]}'
                    outfile.write(f'{line}\n')


def datasetdb():
    # TODO fix me
    os.mkdir('datasetdb')
    os.chdir('orthologs')
    concat_gene_files()
    shutil.move('datasetdb.fasta', '../datasetdb')
    os.chdir('../datasetdb')
    dmd_db = 'diamond makedb --in datasetdb.fasta -d datasetdb'
    subprocess.run(dmd_db, shell=True)
    # os.remove('datasetdb.fasta')
    os.chdir('..')


def make_profiles(threads):
    """
    Prepares hmm profiles from all fasta files with orthologs
    from orthologs folder.

    :param threads: number of threads
    :return: None
    """

    os.mkdir('profiles')
    os.chdir('orthologs')

    # prepares alignments for all fasta files with orthologs
    aln = f'for i in $(ls *.fas); do mafft --auto' \
          f' --thread {threads} --reorder $i > $(basename $i .fas).aln; done'
    subprocess.run(aln, shell=True)

    # prepares hmm profiles from alignmets made in prev. step
    hmm = 'for i in $(ls *.aln); do hmmbuild $(basename $i .aln).hmm $i; done'
    subprocess.run(hmm, shell=True)
    subprocess.run('mv *.hmm ../profiles', shell=True)
    subprocess.run('rm *.aln', shell=True)  # delete alignments
    os.chdir('..')


def main(args, threads, no_og_file, threshold):
    """
    :param args:
    :param threads: number of threads
    :param make_og_file: Boolean
    :param threshold: float 0-1
    :return: None
    """

    # checks if paralogs folder exists and creates
    # it if not
    if os.path.isdir('paralogs') is False:
        os.mkdir('paralogs')
    if os.path.isdir('datasetdb') is True:
        shutil.rmtree('datasetdb')
    if os.path.isdir('profiles') is True:
        shutil.rmtree('profiles')

    if args.rename:
        rename_taxa()

    datasetdb()  # creates datasetdb

    make_profiles(threads)

    if not no_og_file:
        get_og_file(threshold)


if __name__ == "__main__":
    description = 'Script for dataset construction.'
    parser, optional, required = help_formatter.initialize_argparse(name='build_database.py',
                                                                    desc=description,
                                                                    usage='build_database.py [OPTIONS]')

    optional.add_argument('-t', '--threads', type=int,
                          help=textwrap.dedent("""\
                          Number of threads.
                          Default:1
                          """))

    optional.add_argument('-n', '--no_og_file', action='store_true',
                          help=textwrap.dedent("""\
                          Do not make Gene OG file
                          """))
    optional.add_argument('-o', '--og_threshold', type=float, default=0.1, metavar='0.X',
                          help=textwrap.dedent("""\
                          Threshold 0-1 for OG.
                          Default: 0.1
                          """))
    optional.add_argument('--rename', type=str, metavar='<to_rename.tsv>',
                          help=textwrap.dedent("""\
                          Rename taxa in the database.
                          Takes a TSV file containing the Old Unique ID, New Unique ID, and New Long Name.
                          """))

    args = help_formatter.get_args(parser, optional, required, pre_suf=False, inp_dir=False, out_dir=False)

    check_taxa()
    main(args, args.threads, args.no_og_file, args.og_threshold)