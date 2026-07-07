"""Standard line-item -> XBRL (us-gaap) tag mappings for the three core statements.

Each line item lists its primary tag first, followed by fallback tags used by
different filers/taxonomies over time. `unit` constrains which unit of measure
is acceptable for that line item ("USD", "USD/shares", "shares", or "pure" for
ratios such as the effective tax rate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class LineItemMapping:
    name: str
    tags: List[str] = field(default_factory=list)
    unit: str = "USD"


INCOME_STATEMENT: List[LineItemMapping] = [
    LineItemMapping(
        "Revenue",
        [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ],
    ),
    LineItemMapping(
        "Cost of Revenue",
        ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"],
    ),
    LineItemMapping("Gross Profit", ["GrossProfit"]),
    LineItemMapping("Research and Development", ["ResearchAndDevelopmentExpense"]),
    LineItemMapping(
        "Selling General and Administrative",
        [
            "SellingGeneralAndAdministrativeExpense",
            "GeneralAndAdministrativeExpense",
            "SellingAndMarketingExpense",
        ],
    ),
    LineItemMapping("Operating Expenses", ["OperatingExpenses", "CostsAndExpenses"]),
    LineItemMapping("Restructuring Charges", ["RestructuringCharges"]),
    LineItemMapping(
        "Asset Impairment Charges",
        ["AssetImpairmentCharges", "ImpairmentOfIntangibleAssetsExcludingGoodwill"],
    ),
    LineItemMapping("Goodwill Impairment", ["GoodwillImpairmentLoss"]),
    LineItemMapping("Operating Income", ["OperatingIncomeLoss"]),
    LineItemMapping(
        "Interest Expense",
        ["InterestExpense", "InterestExpenseDebt", "InterestIncomeExpenseNet"],
    ),
    LineItemMapping(
        "Total Other Income (Expense), Net",
        ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"],
    ),
    LineItemMapping(
        "Income Before Tax",
        [
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
        ],
    ),
    LineItemMapping("Income Tax Expense", ["IncomeTaxExpenseBenefit"]),
    LineItemMapping(
        "Effective Tax Rate", ["EffectiveIncomeTaxRateContinuingOperations"], unit="pure"
    ),
    LineItemMapping(
        "Net Income",
        ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    ),
    LineItemMapping("EPS Basic", ["EarningsPerShareBasic"], unit="USD/shares"),
    LineItemMapping("EPS Diluted", ["EarningsPerShareDiluted"], unit="USD/shares"),
    LineItemMapping(
        "Weighted Average Shares Basic",
        ["WeightedAverageNumberOfSharesOutstandingBasic"],
        unit="shares",
    ),
    LineItemMapping(
        "Weighted Average Shares Diluted",
        ["WeightedAverageNumberOfDilutedSharesOutstanding"],
        unit="shares",
    ),
]

BALANCE_SHEET: List[LineItemMapping] = [
    LineItemMapping(
        "Cash and Cash Equivalents",
        [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
    ),
    LineItemMapping(
        "Short Term Investments",
        ["ShortTermInvestments", "MarketableSecuritiesCurrent", "OtherShortTermInvestments"],
    ),
    LineItemMapping(
        "Accounts Receivable", ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"]
    ),
    LineItemMapping("Inventory", ["InventoryNet"]),
    LineItemMapping("Other Current Assets", ["OtherAssetsCurrent"]),
    LineItemMapping("Current Assets", ["AssetsCurrent"]),
    LineItemMapping("Property Plant and Equipment", ["PropertyPlantAndEquipmentNet"]),
    LineItemMapping("Goodwill", ["Goodwill"]),
    LineItemMapping(
        "Intangible Assets",
        ["FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill"],
    ),
    LineItemMapping("Other Non-Current Assets", ["OtherAssetsNoncurrent"]),
    LineItemMapping("Non-Current Assets", ["AssetsNoncurrent"]),
    LineItemMapping("Total Assets", ["Assets"]),
    LineItemMapping(
        "Accounts Payable", ["AccountsPayableCurrent", "AccountsPayableTradeCurrent"]
    ),
    LineItemMapping(
        "Deferred Revenue, Current",
        ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"],
    ),
    LineItemMapping("Other Current Liabilities", ["OtherLiabilitiesCurrent"]),
    LineItemMapping("Current Liabilities", ["LiabilitiesCurrent"]),
    LineItemMapping(
        "Long Term Debt",
        [
            "LongTermDebtNoncurrent",
            "LongTermDebt",
            "LongTermDebtNoncurrentAndCapitalLeaseObligationsIncludingCurrentMaturities",
        ],
    ),
    LineItemMapping(
        "Deferred Revenue, Non-Current",
        ["ContractWithCustomerLiabilityNoncurrent", "DeferredRevenueNoncurrent"],
    ),
    LineItemMapping("Other Non-Current Liabilities", ["OtherLiabilitiesNoncurrent"]),
    LineItemMapping("Non-Current Liabilities", ["LiabilitiesNoncurrent"]),
    LineItemMapping("Total Liabilities", ["Liabilities"]),
    LineItemMapping(
        "Common Stock", ["CommonStockValue", "CommonStocksIncludingAdditionalPaidInCapital"]
    ),
    LineItemMapping(
        "Additional Paid-in Capital",
        ["AdditionalPaidInCapital", "AdditionalPaidInCapitalCommonStock"],
    ),
    LineItemMapping("Treasury Stock", ["TreasuryStockValue", "TreasuryStockCommonValue"]),
    LineItemMapping("Retained Earnings", ["RetainedEarningsAccumulatedDeficit"]),
    LineItemMapping(
        "Accumulated Other Comprehensive Income (Loss)",
        ["AccumulatedOtherComprehensiveIncomeLossNetOfTax"],
    ),
    LineItemMapping(
        "Total Stockholders Equity",
        ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    ),
    LineItemMapping("Total Liabilities and Equity", ["LiabilitiesAndStockholdersEquity"]),
    LineItemMapping(
        "Common Shares Outstanding", ["CommonStockSharesOutstanding"], unit="shares"
    ),
]

CASH_FLOW_STATEMENT: List[LineItemMapping] = [
    LineItemMapping("Net Income", ["NetIncomeLoss", "ProfitLoss"]),
    LineItemMapping(
        "Depreciation and Amortization",
        [
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
            "Depreciation",
        ],
    ),
    LineItemMapping("Amortization of Intangible Assets", ["AmortizationOfIntangibleAssets"]),
    LineItemMapping("Stock Based Compensation", ["ShareBasedCompensation"]),
    LineItemMapping("Deferred Income Taxes", ["DeferredIncomeTaxExpenseBenefit"]),
    LineItemMapping("Goodwill Impairment", ["GoodwillImpairmentLoss"]),
    LineItemMapping("Change in Accounts Receivable", ["IncreaseDecreaseInAccountsReceivable"]),
    LineItemMapping("Change in Inventory", ["IncreaseDecreaseInInventories"]),
    LineItemMapping("Change in Accounts Payable", ["IncreaseDecreaseInAccountsPayable"]),
    LineItemMapping(
        "Net Cash Provided by Operating Activities",
        [
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
    ),
    LineItemMapping(
        "Capital Expenditures",
        ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    ),
    LineItemMapping(
        "Purchases of Investments",
        [
            "PaymentsToAcquireInvestments",
            "PaymentsToAcquireShortTermInvestments",
            "PaymentsToAcquireAvailableForSaleSecuritiesDebt",
            "PaymentsToAcquireAvailableForSaleSecurities",
        ],
    ),
    LineItemMapping(
        "Proceeds from Sales/Maturities of Investments",
        [
            "ProceedsFromSaleMaturityAndCollectionsOfInvestments",
            "ProceedsFromSaleOfShortTermInvestments",
            "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",
            "ProceedsFromSaleOfAvailableForSaleSecurities",
        ],
    ),
    LineItemMapping(
        "Acquisitions",
        ["PaymentsToAcquireBusinessesNetOfCashAcquired", "PaymentsToAcquireBusinessesGross"],
    ),
    LineItemMapping(
        "Net Cash Used in Investing Activities", ["NetCashProvidedByUsedInInvestingActivities"]
    ),
    LineItemMapping("Dividends Paid", ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]),
    LineItemMapping("Share Repurchases", ["PaymentsForRepurchaseOfCommonStock"]),
    LineItemMapping(
        "Proceeds from Issuance of Common Stock",
        ["ProceedsFromIssuanceOfCommonStock", "ProceedsFromStockOptionsExercised"],
    ),
    LineItemMapping(
        "Debt Issued",
        [
            "ProceedsFromIssuanceOfLongTermDebt",
            "ProceedsFromIssuanceOfDebt",
            "ProceedsFromDebtMaturingInMoreThanThreeMonths",
            "ProceedsFromConvertibleDebt",
        ],
    ),
    LineItemMapping(
        "Debt Repaid",
        [
            "RepaymentsOfLongTermDebt",
            "RepaymentsOfDebt",
            "RepaymentsOfDebtMaturingInMoreThanThreeMonths",
            "RepaymentsOfConvertibleDebt",
        ],
    ),
    LineItemMapping(
        "Net Cash Provided by Financing Activities",
        ["NetCashProvidedByUsedInFinancingActivities"],
    ),
    LineItemMapping(
        "Effect of Exchange Rate Changes on Cash",
        [
            "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "EffectOfExchangeRateOnCashAndCashEquivalents",
        ],
    ),
    LineItemMapping(
        "Net Change in Cash",
        [
            "CashAndCashEquivalentsPeriodIncreaseDecrease",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        ],
    ),
    LineItemMapping(
        "Cash at End of Period",
        [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
    ),
]

STATEMENT_MAPPINGS = {
    "Income Statement": INCOME_STATEMENT,
    "Balance Sheet": BALANCE_SHEET,
    "Cash Flow Statement": CASH_FLOW_STATEMENT,
}
