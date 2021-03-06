"""Analysis of AIS in a network of processes.

Analysis of active information storage (AIS) in individual processes of a
network. The algorithm uses non-uniform embedding as described in Faes ???.

Note:
    Written for Python 3.4+

@author: patricia
"""
import numpy as np
from . import stats
from .single_process_analysis import SingleProcessAnalysis
from .estimator import find_estimator

# TODO use target instead of process to define the process that is analyzed.
# This would reuse an attribute set in the parent class.


class ActiveInformationStorage(SingleProcessAnalysis):
    """Estimate active information storage in individual processes.

    Estimate active information storage (AIS) in individual processes of the
    network. To perform AIS estimation call analyse_network() on the whole
    network or a set of nodes or call analyse_single_process() to estimate
    AIS for a single process. See docstrings of the two functions for more
    information.

    References:

    - Lizier, J. T., Prokopenko, M., & Zomaya, A. Y. (2012). Local measures of
      information storage in complex distributed computation. Inform Sci, 208,
      39–54. http://doi.org/10.1016/j.ins.2012.04.016
    - Wibral, M., Lizier, J. T., Vögler, S., Priesemann, V., & Galuske, R.
      (2014). Local active information storage as a tool to understand
      distributed neural information processing. Front Neuroinf, 8, 1.
      http://doi.org/10.3389/fninf.2014.00001

    Attributes:
        process_set : list
            list with indices of analyzed processes
        settings : dict
            analysis settings
        current_value : tuple
            index of the current value in AIS estimation, (idx process,
            idx sample)
        selected_vars_full : list of tuples
            samples in the past state, (idx process, idx sample)
        ais : float
            raw AIS value
        sign : bool
            true if AIS is significant
        pvalue: float
            p-value of AIS
    """

    def __init__(self):
        super().__init__()

    def analyse_network(self, settings, data, processes='all'):
        """Estimate active information storage for multiple network processes.

        Estimate active information storage for all or a subset of processes in
        the network.

        Note:
            For a detailed description see the documentation of the
            analyse_single_process() method of this class and the references.

        Example:

            >>> dat = Data()
            >>> dat.generate_mute_data(100, 5)
            >>> settings = {
            >>>     'cmi_estimator': 'JidtKraskovCMI',
            >>>     'n_perm_max_stat': 200,
            >>>     'n_perm_min_stat': 200,
            >>>     'max_lag': 5,
            >>>     'tau': 1
            >>>     }
            >>> processes = [1, 2, 3]
            >>> network_analysis = ActiveInformationStorage()
            >>> res = network_analysis.analyse_network(settings, dat,
            >>>                                        processes)

        Args:
            settings : dict
                parameters for estimation and statistical testing, see
                documentation of analyse_single_process() for details
            data : Data instance
                raw data for analysis
            process : list of int | 'all'
                index of processes (default='all');
                if 'all', AIS is estimated for all processes;
                if list of int, AIS is estimated for processes specified in the
                list.

        Returns:
            dict
                results for each process, see documentation of
                analyse_single_process()
        """
        # Check provided processes for analysis.
        if processes == 'all':
            processes = [t for t in range(data.n_processes)]
        if (type(processes) is list) and (type(processes[0]) is int):
            pass
        else:
            raise ValueError('Processes were not specified correctly: '
                             '{0}.'.format(processes))

        # Perform AIS estimation for each target individually.
        settings.setdefault('verbose', True)
        results = {}
        for t in range(len(processes)):
            if settings['verbose']:
                print('\n####### analysing process {0} of {1}'.format(
                                                processes[t], processes))
            r = self.analyse_single_process(settings, data, processes[t])
            r['process'] = processes[t]
            results[processes[t]] = r
        return results

    def analyse_single_process(self, settings, data, process):
        """Estimate active information storage for a single process.

        Estimate active information storage for one process in the network.
        Uses non-uniform embedding found through information maximisation. This
        is done in three steps (see Lizier and Faes for details):

        (1) find all relevant samples in the processes' own past, by
            iteratively adding candidate samples that have significant
            conditional mutual information (CMI) with the current value
            (conditional on all samples that were added previously)
        (3) prune the final conditional set by testing the CMI between each
            sample in the final set and the current value, conditional on all
            other samples in the final set
        (4) calculate AIS using the final set of candidates as the past state
            (calculate MI between samples in the past and the current value);
            test for statistical significance using a permutation test

        Args:
            settings : dict
                parameters for estimator use and statistics:

                - cmi_estimator : str - estimator to be used for CMI and MI
                  calculation (for estimator settings see the documentation in
                  the estimators_* modules)
                - max_lag : int - maximum temporal search depth for candidates
                  in the processes' past in samples
                - tau : int [optional] - spacing between candidates in the
                  sources' past in samples (default=1)
                - n_perm_* : int [optional] - number of permutations, where *
                  can be 'max_stat', 'min_stat', 'mi' (default=500)
                - alpha_* : float [optional] - critical alpha level for
                  statistical significance, where * can be 'max_stat',
                  'min_stat', 'mi' (default=0.05)
                - add_conditionals : list of tuples | str [optional] - force
                  the estimator to add these conditionals when estimating TE;
                  can either be a list of variables, where each variable is
                  described as (idx process, lag wrt to current value) or can
                  be a string: 'faes' for Faes-Method (see references)
                - permute_in_time : bool [optional] - force surrogate creation
                  by shuffling realisations in time instead of shuffling
                  replications; see documentation of Data.permute_samples() for
                  further settings (default=False)
                - verbose : bool [optional] - toggle console output
                  (default=True)

            data : Data instance
                raw data for analysis
            process : int
                index of process

        Returns:
            dict
                results consisting of sets of selected variables as, the
                current value for this analysis, results for omnibus test
                (joint influence of all selected variables, omnibus TE,
                p-value, and significance); NOTE that all variables are listed
                as tuples (process, lag wrt. current value)
        """
        # Check input and clean up object if it was used before.
        self._initialise(settings, data, process)

        # Main algorithm.
        print('\n---------------------------- (1) include candidates')
        self._include_process_candidates(data)
        print('\n---------------------------- (2) prune source candidates')
        self._prune_candidates(data)
        print('\n---------------------------- (3) final statistics')
        self._test_final_conditional(data)

        # Clean up and return results.
        if self.settings['verbose']:
            print('final conditional samples: {0}'.format(
                    self._idx_to_lag(self.selected_vars_full)))
        results = {
            'current_value': self.current_value,
            'selected_vars': self._idx_to_lag(self.selected_vars_full),
            'ais': self.ais,
            'ais_pval': self.pvalue,
            'ais_sign': self.sign,
            'settings': self.settings}
        self._reset()  # remove realisations and min_stats surrogate table
        return results

    def _initialise(self, settings, data, process):
        """Check input, set initial or default values for analysis settings."""
        # Check analysis settings and set defaults.
        settings.setdefault('verbose', True)
        settings.setdefault('add_conditionals', None)
        settings.setdefault('tau', 1)

        if type(settings['max_lag']) is not int or settings['max_lag'] < 0:
            raise RuntimeError('max_lag has to be an integer >= 0.')
        if type(settings['tau']) is not int or settings['tau'] <= 0:
            raise RuntimeError('tau has to be an integer > 0.')
        if settings['tau'] >= settings['max_lag']:
            raise RuntimeError('tau ({0}) has to be smaller than max_lag ({1})'
                               '.'.format(settings['tau'],
                                          settings['max_lag']))
        self.settings = settings

        # Set CMI estimator.
        try:
            EstimatorClass = find_estimator(settings['cmi_estimator'])
        except KeyError:
            raise RuntimeError('Please provide an estimator class or name!')
        self._cmi_estimator = EstimatorClass(settings)

        # Initialise class attributes.

        self.settings = settings
        self._min_stats_surr_table = None

        # Check process to be analysed.
        if type(process) is not int or process < 0:
            raise RuntimeError('The index of the process ({0}) has to be an '
                               'int >= 0.'.format(process))
        if process > data.n_processes:
            raise RuntimeError('Trying to analyse process with index {0}, '
                               'which greater than the number of processes in '
                               'the data ({1}).'.format(process,
                                                        data.n_processes))
        self.process = process

        # Check provided search depths for source and target
        assert(data.n_samples >= self.settings['max_lag'] + 1), (
            'Not enough samples in data ({0}) to allow for the chosen maximum '
            'lag ({1})'.format(data.n_samples, self.settings['max_lag']))
        self.current_value = (process, self.settings['max_lag'])
        [cv_realisation, repl_idx] = data.get_realisations(
                                             current_value=self.current_value,
                                             idx_list=[self.current_value])
        self._current_value_realisations = cv_realisation

        # Remember which realisations come from which replication. This may be
        # needed for surrogate creation at a later point.
        self._replication_index = repl_idx

        # Check the permutation type and no. permutations requested by the
        # user. This tests if there is sufficient data to do all tests.
        # surrogates.check_permutations(self, data)

        # Reset all attributes to inital values if the instance has been used
        # before.
        if self.selected_vars_full:
            self.selected_vars_full = []
            self.selected_vars_sources = []
            self._selected_vars_realisations = None
            self.pvalue = None
            self.sign = False
            self.ais = None
            self._min_stats_surr_table = None

        # Check if the user provided a list of candidates that must go into
        # the conditioning set. These will be added and used for TE estimation,
        # but never tested for significance.
        if self.settings['add_conditionals'] is not None:
            self._force_conditionals(self.settings['add_conditionals'], data)

    def _include_process_candidates(self, data):
        """Test candidates in the process's past."""
        process = [self.process]
        samples = np.arange(
                    self.current_value[1] - 1,
                    self.current_value[1] - self.settings['max_lag'] - 1,
                    -self.settings['tau'])
        candidates = self._define_candidates(process, samples)
        self._include_candidates(candidates, data)

    def _include_candidates(self, candidate_set, data):
        """Include informative candidates into the conditioning set.

        Loop over each candidate in the candidate set and test if it has
        significant mutual information with the current value, conditional
        on all samples that were informative in previous rounds and are already
        in the conditioning set. If this conditional mutual information is
        significant using maximum statistics, add the current candidate to the
        conditional set.

        Args:
            candidate_set : list of tuples
                candidate set to be tested, where each entry is a tuple
                (process index, sample index)
            data : Data instance
                raw data

        Returns:
            bool
                True if a significant variable was found in the process's past.
        """
        success = False
        while candidate_set:
            # Get realisations for all candidates.
            cand_real = data.get_realisations(self.current_value,
                                              candidate_set)[0]
            cand_real = cand_real.T.reshape(cand_real.size, 1)

            # Calculate the (C)MI for each candidate and the target.
            temp_te = self._cmi_estimator.estimate_mult(
                                n_chunks=len(candidate_set),
                                re_use=['var2', 'conditional'],
                                var1=cand_real,
                                var2=self._current_value_realisations,
                                conditional=self._selected_vars_realisations)

            # Test max CMI for significance with maximum statistics.
            te_max_candidate = max(temp_te)
            max_candidate = candidate_set[np.argmax(temp_te)]
            if self.settings['verbose']:
                print('testing candidate {0} from candidate set {1}'.format(
                                    self._idx_to_lag([max_candidate])[0],
                                    self._idx_to_lag(candidate_set)), end='')
            significant = stats.max_statistic(self, data, candidate_set,
                                              te_max_candidate)[0]

            # If the max is significant keep it and test the next candidate. If
            # it is not significant break. There will be no further significant
            # sources b/c they all have lesser TE.
            if significant:
                if self.settings['verbose']:
                    print(' -- significant')
                success = True
                # Remove candidate from candidate set and add it to the
                # selected variables (used as the conditioning set).
                candidate_set.pop(np.argmax(temp_te))
                self._append_selected_vars(
                        [max_candidate],
                        data.get_realisations(self.current_value,
                                              [max_candidate])[0])
            else:
                if self.settings['verbose']:
                    print(' -- not significant')
                break

        return success

    def _prune_candidates(self, data):
        """Remove uninformative candidates from the final conditional set.

        For each sample in the final conditioning set, check if it is
        informative about the current value given all other samples in the
        final set. If a sample is not informative, it is removed from the
        final set.

        Args:
            data : Data instance
                raw data
        """
        # FOR LATER we don't need to test the last included in the first round
        while self.selected_vars_sources:
            # Find the candidate with the minimum TE into the target.
            cond_dim = len(self.selected_vars_sources) - 1
            candidate_realisations = np.empty(
                                (data.n_realisations(self.current_value) *
                                 len(self.selected_vars_sources), 1))
            conditional_realisations = np.empty(
                                (data.n_realisations(self.current_value) *
                                 len(self.selected_vars_sources), cond_dim))
            i_1 = 0
            i_2 = data.n_realisations(self.current_value)
            for candidate in self.selected_vars_sources:
                # Separate the candidate realisations and all other
                # realisations to test the candidate's individual contribution.
                [temp_cond, temp_cand] = self._separate_realisations(
                                            self.selected_vars_sources,
                                            candidate)
                if temp_cond is None:
                    conditional_realisations = None
                    re_use = ['var2', 'conditional']
                else:
                    conditional_realisations[i_1:i_2, ] = temp_cond
                    re_use = ['var2']
                candidate_realisations[i_1:i_2, ] = temp_cand
                i_1 = i_2
                i_2 += data.n_realisations(self.current_value)

            temp_te = self._cmi_estimator.estimate_mult(
                                    n_chunks=len(self.selected_vars_sources),
                                    re_use=re_use,
                                    var1=candidate_realisations,
                                    var2=self._current_value_realisations,
                                    conditional=conditional_realisations)

            # Test min TE for significance with minimum statistics.
            te_min_candidate = min(temp_te)
            min_candidate = self.selected_vars_sources[np.argmin(temp_te)]
            if self.settings['verbose']:
                print('testing candidate {0} from candidate set {1}'.format(
                                self._idx_to_lag([min_candidate])[0],
                                self._idx_to_lag(self.selected_vars_sources)),
                      end='')
            [significant, p, surr_table] = stats.min_statistic(
                                              self, data,
                                              self.selected_vars_sources,
                                              te_min_candidate)

            # Remove the minimum it is not significant and test the next min.
            # candidate. If the minimum is significant, break, all other
            # sources will be significant as well (b/c they have higher TE).
            if not significant:
                if self.settings['verbose']:
                    print(' -- not significant')
                self._remove_selected_var(min_candidate)
            else:
                if self.settings['verbose']:
                    print(' -- significant')
                self._min_stats_surr_table = surr_table
                break

    def _test_final_conditional(self, data):  # TODO test this!
        """Perform statistical test on AIS using the final conditional set."""
        if self._selected_vars_full:
            print(self._idx_to_lag(self.selected_vars_full))
            [ais, s, p] = stats.mi_against_surrogates(self, data)

            # If a parallel estimator was used, an array of AIS estimates is
            # returned. Make the output uniform for both estimator types.
            if type(ais) is np.ndarray:
                assert ais.shape[0] == 1, 'AIS result is not a scalar.'
                ais = ais[0]

            self.ais = ais
            self.sign = s
            self.pvalue = p
        else:
            self.ais = np.nan
            self.sign = False
            self.pvalue = 1.0

    def _force_conditionals(self, cond, data):
        """Enforce a given conditioning set."""
        if type(cond) is tuple:  # easily add single variable
            cond = [cond]

        print('Adding the following variables to the conditioning set: {0}.'.
              format(self._idx_to_lag(cond)))
        self._append_selected_vars(cond,
                                   data.get_realisations(self.current_value,
                                                         cond)[0])

    def _reset(self):
        """Reset instance after analysis."""
        self.__init__()
        del self.pvalue
        del self.sign
        del self.ais
        del self.settings
        del self._cmi_estimator
