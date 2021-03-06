import argparse
import collections
import sys

try:
     import vcf
except ImportError:
     exit("This script requires the PyVCF python package. Please install using pip or conda")

def records_match(rec_a, rec_b):
     if rec_a.CHROM != rec_b.CHROM:          exit("ERROR: Record chromosomes don't match")
     if rec_a.POS != rec_b.POS:              exit("ERROR: Record positions don't match")
     if rec_a.ID != rec_b.ID:                exit("ERROR: Record IDs don't match")
     if str(rec_a.REF) != str(rec_b.REF):    exit("ERROR: Record REF alleles don't match")
     if len(rec_a.ALT) != len(rec_b.ALT):    exit("ERROR: Record alternate alleles don't match")
     for i in range(len(rec_a.ALT)):
          if str(rec_a.ALT[i]) != str(rec_b.ALT[i]):
               exit("ERROR: Record alternate alleles don't match")

def main():
     parser = argparse.ArgumentParser()
     parser.add_argument("--vcf",              help="Input VCF containing STR genotypes generated by HipSTR", type=str, required=True, dest="VCF")
     parser.add_argument("--denovo-ll-vcf",    help="Input VCF containing log-likelihood for de novo mutations generated by DenovoFinder", type=str, required=True, dest="LLVCF")
     parser.add_argument("--keep-gls",         help="Don't remove the GL, PL or PHASEDGL FORMAT fields from the output VCF (Default = Remove)", action="store_true", default=False, dest="keep_LLs")

     args = parser.parse_args()
     if args.VCF == "-":
          gt_vcf_reader = vcf.Reader(sys.stdin)
     else:
          gt_vcf_reader = vcf.Reader(filename=args.VCF)

     ll_vcf_reader  = vcf.Reader(filename=args.LLVCF)
     all_ll_samples = set(ll_vcf_reader.samples)
     ll_record      = None 

     # Ensure that at least some samples are shared across VCFs
     if len(all_ll_samples.intersection(set(gt_vcf_reader.samples))) == 0:
          exit("ERROR: No samples are shared between the raw VCF and the denovo VCF")

     # Ensure that no FORMAT fields are shared between the two VCFs. Add information about the DenovoFinder FORMAT fields
     # to the HipSTR VCF such that they're appropriately output to the VCF header for the new file
     for k,v in ll_vcf_reader.formats.items():
          if k in gt_vcf_reader.formats:
               exit("ERROR: FORMAT field %s present in both VCFs"%(k))
          gt_vcf_reader.formats[k] = v

     # Open the VCF writer to output the merging results
     vcf_writer = vcf.Writer(sys.stdout, gt_vcf_reader)

     # Iterate through the HipSTR genotype VCF line-by-line
     for gt_record in gt_vcf_reader:
          if ll_record is None:
               ll_record = ll_vcf_reader.next()

          # Skip records if they don't have a corresponding DenovoFinder entry
          if gt_record.CHROM != ll_record.CHROM or gt_record.POS < ll_record.POS:
               continue

          # Verify the records are properly matched
          records_match(gt_record, ll_record)

          gt_fields     = gt_record.FORMAT.split(':')
          denovo_fields = ll_record.FORMAT.split(':')

          # This should be impossible but just check that no FORMAT fields are duplicated
          if len(gt_fields + denovo_fields) != len(gt_fields) + len(denovo_fields):
               exit("ERROR: Duplicate FORMAT fields in the two VCFs")

          if args.keep_LLs:
               fields = gt_fields + denovo_fields
          else:
               fields = list(filter(lambda x: x not in ["GL", "PL", "PHASEDGL"], gt_fields + denovo_fields))

          samp_fmt = vcf.model.make_calldata_tuple(fields)
          in_gt    = []
          for fmt in samp_fmt._fields:
               if fmt in gt_fields:
                    entry_type = gt_vcf_reader.formats[fmt].type
                    entry_num  = gt_vcf_reader.formats[fmt].num
                    in_gt.append(True)
               else:
                    entry_type = ll_vcf_reader.formats[fmt].type
                    entry_num  = ll_vcf_reader.formats[fmt].num
                    in_gt.append(False)
                    
               samp_fmt._types.append(entry_type)
               samp_fmt._nums.append(entry_num)

          # Generate the new sample entries, taking entries from either VCF when appropriate
          new_samples = []
          for sample in gt_record:
               # TO DO: Extend this to include both trio and quad-based calling. Currently only works for trios 
               # b/c quad-based denovo calls are reported on a per-family basis

               # Obtain the matching DenovoFinder record entry
               ll_sample = ll_record.genotype(sample.sample) if sample.sample in all_ll_samples else None

               sampdat = []
               for i in range(len(samp_fmt._fields)):
                    key = samp_fmt._fields[i]
                    if in_gt[i]:
                         sampdat.append(sample[key])
                    else:
                         sampdat.append("." if ll_sample is None else ll_sample[key])

               call = vcf.model._Call(gt_record, sample.sample, samp_fmt(*sampdat))
               new_samples.append(call)
               
          gt_record.FORMAT  = ":".join(fields)
          gt_record.samples = new_samples

          # Output the result
          vcf_writer.write_record(gt_record)

          # Prepare to process the next DenovoFinder entry
          ll_record = None

if __name__ == "__main__":
     main()
