# ----------------------------------------------------------------------------
# Copyright (C) 2021-2023 Deepchecks (https://www.deepchecks.com)
#
# This file is part of Deepchecks.
# Deepchecks is distributed under the terms of the GNU Affero General
# Public License (version 3 or later).
# You should have received a copy of the GNU Affero General Public License
# along with Deepchecks.  If not, see <http://www.gnu.org/licenses/>.
# ----------------------------------------------------------------------------
#
"""String mismatch functions."""
import itertools
from collections import defaultdict
from typing import Dict, List, Optional, Union

import pandas as pd

from deepchecks.core import CheckResult, ConditionCategory, ConditionResult
from deepchecks.core.fix_classes import SingleDatasetCheckFixMixin
from deepchecks.core.reduce_classes import ReduceFeatureMixin
from deepchecks.tabular import Context, SingleDatasetCheck
from deepchecks.tabular._shared_docs import docstrings
from deepchecks.tabular.utils.feature_importance import N_TOP_MESSAGE, column_importance_sorter_df
from deepchecks.tabular.utils.messages import get_condition_passed_message
from deepchecks.utils.dataframes import select_from_dataframe
from deepchecks.utils.strings import format_percent, get_base_form_to_variants_dict, is_string_column
from deepchecks.utils.typing import Hashable

__all__ = ['StringMismatch']


@docstrings
class StringMismatch(SingleDatasetCheck, ReduceFeatureMixin, SingleDatasetCheckFixMixin):
    """Detect different variants of string categories (e.g. "mislabeled" vs "mis-labeled") in a categorical column.

    This check tests all the categorical columns within a dataset and search for variants of similar strings.
    Specifically, we define similarity between strings if they are equal when ignoring case and non-letter
    characters.
    Example:
    We have a column with similar strings 'OK' and 'ok.' which are variants of the same category. Knowing they both
    exist we can fix our data so it will have only one category.

    Parameters
    ----------
    columns : Union[Hashable, List[Hashable]] , default: None
        Columns to check, if none are given checks all columns except ignored ones.
    ignore_columns : Union[Hashable, List[Hashable]] , default: None
        Columns to ignore, if none given checks based on columns variable
    n_top_columns : int , optional
        amount of columns to show ordered by feature importance (date, index, label are first)
    aggregation_method: t.Optional[str], default: 'max'
        {feature_aggregation_method_argument:2*indent}
    n_samples : int , default: 1_000_000
        number of samples to use for this check.
    random_state : int, default: 42
        random seed for all check internals.
    """

    def __init__(
            self,
            columns: Union[Hashable, List[Hashable], None] = None,
            ignore_columns: Union[Hashable, List[Hashable], None] = None,
            n_top_columns: int = 10,
            aggregation_method: Optional[str] = 'max',
            n_samples: int = 1_000_000,
            random_state: int = 42,
            **kwargs
    ):
        super().__init__(**kwargs)
        self.columns = columns
        self.ignore_columns = ignore_columns
        self.n_top_columns = n_top_columns
        self.aggregation_method = aggregation_method
        self.n_samples = n_samples
        self.random_state = random_state

    def run_logic(self, context: Context, dataset_kind) -> CheckResult:
        """Run check."""
        dataset = context.get_data_by_kind(dataset_kind)
        df = select_from_dataframe(dataset.sample(self.n_samples, random_state=self.random_state).data,
                                   self.columns, self.ignore_columns)

        feature_importance = context.feature_importance if context.feature_importance is not None \
            else pd.Series(index=list(df.columns), dtype=object)

        display_results = []
        result_dict = {'n_samples': len(df), 'columns': {}, 'feature_importance': feature_importance}

        for column_name in df.columns:
            column: pd.Series = df[column_name]
            if not is_string_column(column):
                continue

            result_dict['columns'][column_name] = {}
            value_counts = column.value_counts()
            uniques = column.unique()
            base_form_to_variants = get_base_form_to_variants_dict(uniques)
            for base_form, variants in base_form_to_variants.items():
                if len(variants) == 1:
                    continue
                result_dict['columns'][column_name][base_form] = []
                for variant in variants:
                    count = value_counts[variant]
                    percent = count / len(column)
                    result_dict['columns'][column_name][base_form].append({
                        'variant': variant, 'count': count, 'percent': percent
                    })
                    if context.with_display:
                        display_results.append([column_name, base_form, variant, count, format_percent(percent)])

        # Create dataframe to display graph
        if display_results:
            df_graph = pd.DataFrame(display_results, columns=['Column Name', 'Base form', 'Value', 'Count',
                                                              '% In data'])
            df_graph = df_graph.set_index(['Column Name', 'Base form'])
            df_graph = column_importance_sorter_df(df_graph, dataset, context.feature_importance,
                                                   self.n_top_columns, col='Column Name')
            display = [N_TOP_MESSAGE % self.n_top_columns, df_graph]
        else:
            display = None

        return CheckResult(result_dict, display=display)

    def reduce_output(self, check_result: CheckResult) -> Dict[str, float]:
        """Return an aggregated drift score based on aggregation method defined."""
        feature_importance = check_result.value['feature_importance']

        if check_result.value['columns']:
            total_mismatched = {column: sum([sum(x['count'] for x in check_result.value['columns'][column][base_form])
                                             for base_form in check_result.value['columns'][column]])
                                for column in check_result.value['columns']}
        else:
            total_mismatched = {column: 0 for column in check_result.value['columns']}

        percent_mismatched = pd.Series({column: total_mismatched[column] / check_result.value['n_samples'] for column in
                                        check_result.value['columns']})
        return self.feature_reduce(self.aggregation_method, percent_mismatched, feature_importance,
                                   'Percent Mismatched Strings')

    def add_condition_number_variants_less_or_equal(self, num_max_variants: int):
        """Add condition - number of variants (per string baseform) is less or equal to threshold.

        Parameters
        ----------
        num_max_variants : int
            Maximum number of variants allowed.
        """
        name = f'Number of string variants is less or equal to {num_max_variants}'
        return self.add_condition(name, _condition_variants_number, num_max_variants=num_max_variants)

    def add_condition_no_variants(self):
        """Add condition - no variants are allowed."""
        name = 'No string variants'
        return self.add_condition(name, _condition_variants_number, num_max_variants=0)

    def add_condition_ratio_variants_less_or_equal(self, max_ratio: float = 0.01):
        """Add condition - percentage of variants in data is less or equal to threshold.

        Parameters
        ----------
        max_ratio : float , default: 0.01
            Maximum percent of variants allowed in data.
        """

        def condition(result, max_ratio: float):
            not_passing_columns = {}
            for col, baseforms in result['columns'].items():
                variants_percent_sum = 0
                for variants_list in baseforms.values():
                    variants_percent_sum += sum([v['percent'] for v in variants_list])
                if variants_percent_sum > max_ratio:
                    not_passing_columns[col] = format_percent(variants_percent_sum)

            if not_passing_columns:
                details = f'Found {len(not_passing_columns)} out of {len(result["columns"])} relevant columns with ' \
                          f'variants ratio above threshold: {not_passing_columns}'
                return ConditionResult(ConditionCategory.FAIL, details)
            return ConditionResult(ConditionCategory.PASS, get_condition_passed_message(result['columns']))

        name = f'Ratio of variants is less or equal to {format_percent(max_ratio)}'
        return self.add_condition(name, condition, max_ratio=max_ratio)

    def fix_logic(self, context: Context, check_result, dataset_kind) -> Context:
        """Run fix."""
        dataset = context.get_data_by_kind(dataset_kind)
        data = dataset.data.copy()

        for col, variants in check_result.value['columns'].items():
            for baseform, details in variants.items():
                most_common_variant = sorted([(var['variant'], var['percent']) for var in details],
                                             key=lambda x: x[1], reverse=True)[0][0]
                all_variants = [var['variant'] for var in details]
                data[col] = data[col].apply(lambda x: most_common_variant if x in all_variants else x)

        context.set_dataset_by_kind(dataset_kind, dataset.copy(data))
        return context

    @property
    def fix_params(self):
        """Return fix params for display."""
        return {}

    @property
    def problem_description(self):
        """Return problem description."""
        return """String variants are found in data. This can be caused by typos, different ways of writing the same
                  thing, etc. This can decrease model performance as the model cannot connect the different variants."""

    @property
    def manual_solution_description(self):
        """Return manual solution description."""
        return """Change variants to the preferred form of original string."""

    @property
    def automatic_solution_description(self):
        """Return automatic solution description."""
        return """In each column, change each variant to the most common one."""


def _condition_variants_number(result, num_max_variants: int, max_cols_to_show: int = 5, max_forms_to_show: int = 5):
    not_passing_variants = defaultdict(list)
    for col, baseforms in result['columns'].items():
        for base_form, variants_list in baseforms.items():
            if len(variants_list) > num_max_variants:
                if len(not_passing_variants[col]) < max_forms_to_show:
                    not_passing_variants[col].append(base_form)
    if not_passing_variants:
        variants_to_show = dict(itertools.islice(not_passing_variants.items(), max_cols_to_show))
        details = f'Found {len(not_passing_variants)} out of {len(result["columns"])} columns with amount of ' \
                  f'variants above threshold: {variants_to_show}'
        return ConditionResult(ConditionCategory.WARN, details)

    return ConditionResult(ConditionCategory.PASS, get_condition_passed_message(['columns']))
