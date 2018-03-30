import os
import sys
import minus80 as m80
import locuspocus as lp
import asyncio

#basepath = '/root'

#if not m80.Tools.available('Cohort','EMS_Muscle_Fat'):
#    ems_cohort = m80.Cohort.from_yaml(
#		    'EMS_Muscle_Fat',
#		    os.path.join(basepath,'data/MDB.yaml')
#		)
#else:
#    ems_cohort = m80.Cohort('EMS_Muscle_Fat')
#
#genome_dir = '/project/Data/Fasta/STARIndices/EquCab3' 
#out_dir = "/output/"

class wc_protocol(asyncio.SubprocessProtocol):
    '''
        IO protocol for the word cound program
    '''
    def __init__(self,exit_future):
        self.exit_future = exit_future
        self.output = bytearray()
        self.num_lines = None

    def pipe_data_received(self, fd, data):
        self.output.extend(data)
        #print(data)
        self.num_lines = int(data.decode('ascii').rstrip().split()[0])

    def process_exited(self):
        self.exit_future.set_result(True)




class STARMap(object):
    '''
        Maps RNASeq based on LinkageIO Cohorts
    '''
    def __init__(self, basepath, genome_dir, out_dir):
        self.basepath = basepath
        self.genome_dir = genome_dir
        self.out_dir = out_dir
        # Define some config stats
        self.sem = asyncio.Semaphore(4)
        self.loop = asyncio.get_event_loop()
        # Allocate this for later
        self.cohort = None


    async def create_genome_index(self):
        # Create a genome index
        async with self.sem:
            exit_future = asyncio.Future(loop=self.loop)
            print('Indexing Genome for STAR',file=sys.stdout)
            STAR_index_EquCab3_cmd = '''\
                STAR \
                --runThreadN 7 \
                --runMode genomeGenerate \
                --genomeDir /project/Data/Fasta/STARIndices/EquCab3 \
                --genomeFastaFiles /project/Data/Fasta/EquCab3/EquCab3.fasta \
                --sjdbGTFfile /project/Data/GFFs/ref_EquCab3.0_top_level.gff3 \
                --sjdbGTFtagExonParentTranscript Parent \
            '''

    async def map_sample(self,sample):
        '''
            runs wc on r1 and r2 
        '''
        # bound the number of samples using a semaphore
        async with self.sem:
            # Check that FASTQ files occur in pairs 
            if len(sample.files) % 2 != 0:
                raise ValueError('The number of FASTQ files must be the SAME!!')
            # Generate the files from each paired end read 
            R1s = [x for x in sample.files if 'R1' in x]
            R2s = [x.replace('R1','R2') for x in R1s]
            # Loop through and could the number of lines in each
            print(f'Counting lines for {sample.name}')
            for r1,r2 in zip(R1s,R2s):
                # Get the number of lines in R1
                wc_1_future = asyncio.Future(loop=self.loop)
                wc_r1 = self.loop.subprocess_exec(
                    lambda: wc_protocol(wc_1_future),
                    'wc', '-l', r1,
                    stdin=None, stdout=None
                )
                transport1, protocol1 = await wc_r1
                await wc_1_future
                transport1.close()
                num_r1 = protocol1.num_lines
                print(f'{r1} has {num_r1} lines')
                # Get the number of lines in R2
                wc_2_future = asyncio.Future(loop=self.loop)
                wc_r2 = self.loop.subprocess_exec(
                    lambda: wc_protocol(wc_2_future),
                    'wc', '-l', r2,
                    stdin=None,stdout=None
                )
                transport2, protocol2 = await wc_r2
                await wc_2_future
                transport2.close()
                num_r2 = protocol2.num_lines
                print(f'{r2} has {num_r2} lines')
                # Compare the number of lines in R1 and R2
                if num_r1 != num_r2:
                    raise ValueError(f'{r1} and {r2} must have the same number of lines')
                bam_name = os.path.basename(r1).replace('_R1','').replace('.fastq','')
                output_dir = os.path.join(out_dir,bam_name+'/')
                os.makedirs(output_dir,exist_ok=True)
                if not os.path.exists(os.path.join(output_dir,'Aligned.sortedByCoord.out.bam')):
                    print(f'Mapping for {sample.name}')
                #    cmd = f'''\
                #        STAR \
                #        --runThreadN 3 \
                #        --genomeDir {genome_dir} \
                #        --readFilesIn {r1} {r2} \
                #        --outReadsUnmapped Fastx \
                #        --outFileNamePrefix  {output_dir} \
                #        --outSAMtype BAM SortedByCoordinate \
                #    '''

    def run(self, cohort):
        self.cohort = cohort
        # Define a task for each sample in the cohort
        tasks = []
        for sample in self.cohort:
            # Create a task for each sample
            task = self.map_sample(sample)
            tasks.append(task)
        # Gather the tasks
        results = asyncio.gather(*tasks)
        # run them in the loop
        self.loop.run_until_complete(results)

