import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO
from sklearn.preprocessing import MinMaxScaler
import yfinance as yf
import calendar
from datetime import datetime, timedelta
from scipy.optimize import minimize

def initialize_session_state():
    """Initialize all session state variables"""
    state_vars = {
        'step': 1,
        'data': None,
        'cleaned_data': None,
        'normalized_data': None,
        'normalized_columns': None,
        'normalization_completed': False,
        'weights': {},
        'ranked_data': None,
        'selected_stocks': None,
        'returns_data': None,
        'closing_prices': None,
        'covariance_matrix': None,
        'trading_days_metrics': None
    }
    
    for var, default in state_vars.items():
        if var not in st.session_state:
            st.session_state[var] = default

def analyze_trading_days(returns_data):
    """Analyze trading days distribution and patterns"""
    start_date = returns_data.index.min()
    end_date = returns_data.index.max()
    total_calendar_days = (end_date - start_date).days + 1
    trading_days = len(returns_data)
    
    trading_days_ratio = trading_days / 252
    
    monthly_trading_days = returns_data.groupby(
        [returns_data.index.year, returns_data.index.month]
    ).size()
    monthly_trading_days.index = [
        f"{calendar.month_name[m]} {y}" 
        for y, m in monthly_trading_days.index
    ]
    
    months_spanned = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1
    expected_trading_days = months_spanned * 21
    
    all_days = pd.date_range(start=start_date, end=end_date, freq='B')
    missing_days = all_days.difference(returns_data.index)
    
    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_calendar_days': total_calendar_days,
        'total_trading_days': trading_days,
        'trading_days_ratio': trading_days_ratio,
        'expected_trading_days': expected_trading_days,
        'monthly_trading_days': monthly_trading_days,
        'missing_days': missing_days
    }

def analyze_covariance_for_optimization(covariance_matrix, returns_data):
    """Analyze covariance matrix properties for optimization"""
    eigenvalues = np.linalg.eigvals(covariance_matrix)
    
    correlation_matrix = returns_data.corr()
    mask = ~np.eye(correlation_matrix.shape[0], dtype=bool)
    
    return {
        'is_positive_definite': np.all(eigenvalues > 0),
        'condition_number': np.linalg.cond(covariance_matrix),
        'is_symmetric': np.allclose(covariance_matrix, covariance_matrix.T),
        'min_correlation': correlation_matrix.values[mask].min(),
        'max_correlation': correlation_matrix.values[mask].max(),
        'smallest_eigenvalue': eigenvalues.min(),
        'largest_eigenvalue': eigenvalues.max()
    }

def clean_data(df):
    """Clean the dataset and return cleaning statistics"""
    cleaning_stats = {
        'initial_rows': len(df),
        'removed_rows': {},
        'final_rows': 0
    }
    
    df_cleaned = df.copy()
    preserve_columns = ['Stock', 'Market Capitalization', 'Industry', 'NSE Code', 'BSE Code', 'ISIN']
    columns_to_clean = [col for col in df.columns if col not in preserve_columns]
    
    for col in columns_to_clean:
        if pd.api.types.is_numeric_dtype(df_cleaned[col]):
            neg_mask = df_cleaned[col] < 0
            neg_count = neg_mask.sum()
            if neg_count > 0:
                cleaning_stats['removed_rows'][f'Negative values in {col}'] = neg_count
            
            null_count = df_cleaned[col].isnull().sum()
            if null_count > 0:
                cleaning_stats['removed_rows'][f'Missing values in {col}'] = null_count
            
            df_cleaned = df_cleaned[~neg_mask & df_cleaned[col].notnull()]
    
    cleaning_stats['final_rows'] = len(df_cleaned)
    cleaning_stats['total_removed'] = cleaning_stats['initial_rows'] - cleaning_stats['final_rows']
    
    return df_cleaned, cleaning_stats

def normalize_data(df, columns_to_normalize, columns_to_invert):
    """Normalize selected columns using MinMaxScaler"""
    df_normalized = df.copy()
    scaler = MinMaxScaler()
    
    for column in columns_to_normalize:
        if column in columns_to_invert:
            df_normalized[column] = -1 * df_normalized[column]
        df_normalized[[column]] = scaler.fit_transform(df_normalized[[column]])
    
    return df_normalized

def calculate_composite_score(df, columns_for_composite_score, weights):
    """Calculate composite score with weights"""
    weight_array = np.array([weights[col] for col in columns_for_composite_score])
    weight_array = weight_array / 100
    weighted_scores = df[columns_for_composite_score].multiply(weight_array, axis=1)
    return weighted_scores.sum(axis=1)

def plot_normalized_comparison(df, df_normalized, column):
    """Create comparison plot of original vs normalized values"""
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=df[column], name='Original', nbinsx=30, opacity=0.7))
    fig.add_trace(go.Histogram(x=df_normalized[column], name='Normalized', nbinsx=30, opacity=0.7))
    fig.update_layout(
        barmode='overlay',
        title=f"Distribution of {column}",
        xaxis_title="Value",
        yaxis_title="Count"
    )
    return fig

def handle_data_import():
    """Handle data import and preprocessing"""
    st.header("Step 1: Data Import & Preprocessing")
    
    uploaded_file = st.file_uploader("Upload your CSV file", type=['csv'])
    
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.subheader("Initial Data Overview")
            
            col1, col2 = st.columns(2)
            with col1:
                st.write("First few rows of raw data:")
                st.dataframe(df.head())
            with col2:
                st.write("Column Information:")
                col_info = pd.DataFrame({
                    'Data Type': df.dtypes.astype(str),
                    'Non-Null Count': df.count().astype(int),
                    'Null Count': df.isnull().sum().astype(int)
                })
                st.dataframe(col_info)
            
            df_cleaned, cleaning_stats = clean_data(df)
            st.subheader("Data Cleaning Summary")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Initial Rows", cleaning_stats['initial_rows'])
            with col2:
                st.metric("Rows Removed", cleaning_stats['total_removed'])
            with col3:
                st.metric("Final Rows", cleaning_stats['final_rows'])
            
            if cleaning_stats['removed_rows']:
                st.write("Detailed Breakdown of Removed Rows:")
                removal_data = pd.DataFrame(
                    list(cleaning_stats['removed_rows'].items()),
                    columns=['Reason', 'Number of Rows']
                )
                removal_data['Percentage'] = (removal_data['Number of Rows'] / cleaning_stats['initial_rows'] * 100).round(2)
                removal_data['Percentage'] = removal_data['Percentage'].astype(str) + '%'
                st.dataframe(removal_data, hide_index=True)
                
                if cleaning_stats['total_removed'] / cleaning_stats['initial_rows'] > 0.2:
                    st.warning("⚠️ Significant amount of data was removed during cleaning. Please review your data quality.")
            else:
                st.success("No rows were removed during cleaning! Your data was already clean.")
            
            if len(df_cleaned) > 0:
                st.subheader("Cleaned Data Preview")
                st.dataframe(df_cleaned.head())
                st.session_state.cleaned_data = df_cleaned
                
                if st.button("Proceed to Normalization"):
                    st.session_state.step = 2
                    st.rerun()
            else:
                st.error("No data remains after cleaning! Please check your input data.")
                
        except Exception as e:
            st.error("Error processing file:")
            st.error(str(e))

def handle_normalization():
    """Handle the normalization step"""
    if st.session_state.cleaned_data is None:
        st.warning("Please complete the data import and cleaning step first.")
        return
    
    st.header("Step 2: Data Normalization")
    df = st.session_state.cleaned_data
    
    preserve_columns = ['Stock', 'Market Capitalization', 'Industry', 'NSE Code', 'BSE Code', 'ISIN']
    numeric_columns = df.select_dtypes(include=['float64', 'int64']).columns
    numeric_columns = [col for col in numeric_columns if col not in preserve_columns]
    
    columns_to_normalize = st.multiselect(
        "Select columns to normalize",
        options=numeric_columns,
        default=numeric_columns,
        key='normalize_columns'
    )
    
    if columns_to_normalize:
        columns_to_invert = st.multiselect(
            "Select columns where lower values are better",
            options=columns_to_normalize,
            key='invert_columns'
        )
        
        if st.button("Apply Normalization", key="normalize_button"):
            try:
                df_normalized = normalize_data(df, columns_to_normalize, columns_to_invert)
                st.session_state.normalized_data = df_normalized
                st.session_state.normalized_columns = columns_to_normalize
                st.session_state.normalization_completed = True
                
                st.success("Normalization completed successfully!")
                
                st.subheader("Normalization Results")
                col1, col2 = st.columns(2)
                with col1:
                    st.write("Before Normalization (First 5 rows)")
                    st.dataframe(df[columns_to_normalize].head())
                with col2:
                    st.write("After Normalization (First 5 rows)")
                    st.dataframe(df_normalized[columns_to_normalize].head())
                
                st.subheader("Distribution Comparison")
                selected_col = st.selectbox(
                    "Select column to visualize",
                    columns_to_normalize,
                    key='distribution_column'
                )
                fig = plot_normalized_comparison(df, df_normalized, selected_col)
                st.plotly_chart(fig)
                
            except Exception as e:
                st.error(f"Error during normalization: {str(e)}")
    else:
        st.warning("Please select at least one column to normalize.")
    
    if st.session_state.normalization_completed:
        if st.button("Proceed to Composite Score", key="proceed_to_composite"):
            st.session_state.step = 3
            st.rerun()

def handle_composite_score():
    """Handle the composite score calculation step"""
    if not st.session_state.normalization_completed:
        st.warning("Please complete the normalization step first.")
        return
    
    st.header("Step 3: Composite Score Calculation")
    df = st.session_state.normalized_data
    normalized_columns = st.session_state.normalized_columns
    
    st.subheader("Configure Weights")
    st.write("Assign weights to each normalized metric (total should sum to 100%)")
    
    cols = st.columns(3)
    weights = {}
    total_weight = 0
    
    for idx, col in enumerate(normalized_columns):
        with cols[idx % 3]:
            weight = st.number_input(
                f"Weight for {col} (%)",
                min_value=0.0,
                max_value=100.0,
                value=100.0/len(normalized_columns),
                step=0.1,
                key=f"weight_{idx}"
            )
            weights[col] = weight
            total_weight += weight
    
    st.metric("Total Weight", f"{total_weight:.1f}%")
    
    if abs(total_weight - 100) > 0.1:
        st.error("Total weight must equal 100%")
        return
    
    st.success("Weights are properly distributed")
    
    if st.button("Calculate Composite Score", key="calc_composite_score"):
        try:
            df['Composite Score'] = calculate_composite_score(df, normalized_columns, weights)
            df['Rank'] = df['Composite Score'].rank(ascending=False)
            df_ranked = df.sort_values('Composite Score', ascending=False)
            
            st.session_state.ranked_data = df_ranked
            st.session_state.weights = weights
            
            st.success("Composite scores calculated successfully!")
            
            st.subheader("Top 10 Stocks by Composite Score")
            display_cols = ['Stock', 'Composite Score', 'Rank']
            st.dataframe(df_ranked[display_cols].head(10))
            
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_ranked.to_excel(writer, index=False)
            
            st.download_button(
                label="Download Complete Results",
                data=output.getvalue(),
                file_name="composite_scores.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
                
        except Exception as e:
            st.error(f"Error calculating composite score: {str(e)}")
    
    if 'ranked_data' in st.session_state and st.session_state.ranked_data is not None:
        if st.button("Proceed to Stock Selection", key="proceed_to_selection"):
            st.session_state.step = 4
            st.rerun()

def handle_stock_selection():
    """Handle the stock selection step"""
    if 'ranked_data' not in st.session_state:
        st.warning("Please complete the composite score calculation first.")
        return
    
    st.header("Step 4: Stock Selection")
    df_ranked = st.session_state.ranked_data
    
    percentile_threshold = st.slider(
        "Select percentile threshold for stock selection",
        min_value=1,
        max_value=100,
        value=60,
        help="Stocks above this percentile will be selected"
    )
    
    percentile_value = np.percentile(
        df_ranked['Composite Score'],
        percentile_threshold,
        method='linear'
    )
    
    df_selected = df_ranked[df_ranked['Composite Score'] > percentile_value].copy()
    
    # Update Market Cap Category assignment
    df_selected['Market Cap Category'] = pd.cut(
        df_selected['Market Capitalization'],
        bins=[-np.inf, 29182.71, 89123.03, np.inf],
        labels=['Small-Cap', 'Mid-Cap', 'Large-Cap'],
        include_lowest=True
    )
    df_selected['Market Cap Category'] = df_selected['Market Cap Category'].astype(str)
    
    st.subheader("Selection Results")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Stocks Selected", len(df_selected))
    with col2:
        st.metric("Selection Cutoff Score", f"{percentile_value:.4f}")
    with col3:
        st.metric("Selected Portfolio %", f"{(len(df_selected)/len(df_ranked))*100:.1f}%")
    
    st.subheader("Market Cap Distribution")
    cap_distribution = df_selected['Market Cap Category'].value_counts()
    cap_distribution_pct = df_selected['Market Cap Category'].value_counts(normalize=True) * 100
    
    cap_dist_df = pd.DataFrame({
        'Market Cap Category': cap_distribution.index,
        'Count': cap_distribution.values,
        'Percentage': cap_distribution_pct.values.round(2)
    })
    st.dataframe(cap_dist_df)
    
    st.subheader("Selection Cutoff Visualization")
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=df_ranked['Composite Score'],
        name='All Stocks',
        nbinsx=50,
        opacity=0.7
    ))
    fig.add_trace(go.Histogram(
        x=df_selected['Composite Score'],
        name='Selected Stocks',
        nbinsx=50,
        opacity=0.7
    ))
    fig.add_vline(
        x=percentile_value,
        line_dash="dash",
        annotation_text=f"Selection Cutoff ({percentile_threshold}th percentile)",
        line_color="red"
    )
    fig.update_layout(
        title="Distribution of Composite Scores",
        xaxis_title="Composite Score",
        yaxis_title="Count",
        barmode='overlay'
    )
    st.plotly_chart(fig)
    
    st.subheader("Selected Stocks")
    display_cols = ['Stock', 'NSE Code', 'BSE Code', 'Industry', 
                   'Market Capitalization', 'Market Cap Category', 
                   'Composite Score', 'Rank']
    st.dataframe(df_selected[display_cols])
    
    if st.button("Proceed to Returns Analysis"):
        st.session_state.selected_stocks = df_selected
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_ranked.to_excel(writer, sheet_name='All Stocks', index=False)
            df_selected.to_excel(writer, sheet_name='Selected Stocks', index=False)
            
            summary_data = {
                'Metric': ['Selection Percentile', 'Cutoff Score', 'Total Stocks Selected'],
                'Value': [percentile_threshold, percentile_value, len(df_selected)]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Selection Summary', index=False)
            cap_dist_df.to_excel(writer, sheet_name='Market Cap Distribution', index=False)
        
        st.download_button(
            label="Download Selection Results",
            data=output.getvalue(),
            file_name="stock_selection_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.session_state.step = 5
        st.rerun()

def handle_returns_analysis():
    """Handle the returns analysis step with daily returns data"""
    if 'selected_stocks' not in st.session_state:
        st.warning("Please complete the stock selection step first.")
        if st.button("Return to Stock Selection"):
            st.session_state.step = 4
            st.rerun()
        return
    
    st.header("Step 5: Returns Analysis")
    
    selected_stocks = st.session_state.selected_stocks
    
    def get_stock_symbol(row):
        return row['NSE Code'] if pd.notna(row['NSE Code']) else row['BSE Code']
    
    selected_stocks['Symbol'] = selected_stocks.apply(get_stock_symbol, axis=1)
    
    st.subheader("Historical Data Configuration")
    end_date = st.date_input("End Date (Last Trading Day)", value=pd.Timestamp.now())
    start_date = end_date - pd.Timedelta(days=365)
    
    try:
        with st.spinner("Fetching historical stock data..."):
            progress_bar = st.progress(0)
            returns_data = pd.DataFrame()
            closing_prices = pd.DataFrame()
            
            for i, symbol in enumerate(selected_stocks['Symbol']):
                yahoo_symbol = f"{symbol}.NS" if symbol in selected_stocks['NSE Code'].values else f"{symbol}.BO"
                
                try:
                    stock_data = yf.download(yahoo_symbol, start=start_date, end=end_date)
                    if not stock_data.empty:
                        closing_prices[symbol] = stock_data['Adj Close']
                        returns_data[symbol] = stock_data['Adj Close'].pct_change()
                except Exception as e:
                    st.warning(f"Could not fetch data for {symbol}: {str(e)}")
                
                progress_bar.progress((i + 1) / len(selected_stocks['Symbol']))
        
        if returns_data.empty:
            st.error("Could not fetch returns data for any stocks.")
            return
        
        trading_metrics = analyze_trading_days(returns_data)
        
        st.subheader("Trading Days Analysis")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Trading Days", trading_metrics['total_trading_days'])
        with col2:
            st.metric("Trading Days Ratio", f"{trading_metrics['trading_days_ratio']:.2f}")
        with col3:
            st.metric("Calendar Days", trading_metrics['total_calendar_days'])
        with col4:
            st.metric("Expected Trading Days", trading_metrics['expected_trading_days'])
        
        daily_tab, stats_tab, matrix_tab = st.tabs(["Daily Returns", "Statistics", "Covariance Matrix"])
        
        with daily_tab:
            formatted_returns = returns_data.copy()
            formatted_returns = formatted_returns.multiply(100).round(2)
            
            with st.expander("View Complete Daily Returns Table", expanded=False):
                formatted_returns_display = formatted_returns.copy()
                formatted_returns_display.index = formatted_returns_display.index.strftime('%Y-%m-%d')
                st.dataframe(formatted_returns_display, height=400)
            
            st.subheader("Recent Daily Returns (Last 5 Trading Days)")
            recent_returns = formatted_returns.tail(5)
            recent_returns.index = recent_returns.index.strftime('%Y-%m-%d')
            st.dataframe(recent_returns)
        
        with stats_tab:
            st.subheader("Returns Statistics (%)")
            returns_stats = returns_data.agg([
                'mean', 'std', 'min', 'max', 
                lambda x: x.quantile(0.25),
                lambda x: x.quantile(0.75)
            ]).multiply(100).round(2)
            
            returns_stats.index = [
                'Average Daily Return %', 
                'Daily Volatility %', 
                'Minimum Daily Return %', 
                'Maximum Daily Return %',
                '25th Percentile %',
                '75th Percentile %'
            ]
            st.dataframe(returns_stats)
            
            fig = go.Figure()
            for column in returns_data.columns:
                fig.add_trace(go.Box(
                    y=returns_data[column].multiply(100),
                    name=column,
                    boxpoints='outliers'
                ))
            fig.update_layout(
                title="Distribution of Daily Returns by Stock",
                yaxis_title="Daily Returns (%)",
                showlegend=False,
                height=600
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with matrix_tab:
            st.subheader("Covariance Matrix Analysis")
            correlation_matrix = returns_data.corr()
            
            fig_corr = px.imshow(
                correlation_matrix,
                labels=dict(x="Stock", y="Stock", color="Correlation"),
                color_continuous_scale="RdBu",
                aspect="auto"
            )
            fig_corr.update_layout(title="Correlation Heatmap")
            st.plotly_chart(fig_corr, use_container_width=True)
            
            st.write(f"Annualized Covariance Matrix (Based on {trading_metrics['total_trading_days']} trading days)")
            covariance_matrix = returns_data.cov() * trading_metrics['total_trading_days']
            
            fig_cov = px.imshow(
                covariance_matrix,
                labels=dict(x="Stock", y="Stock", color="Covariance"),
                color_continuous_scale="Viridis",
                aspect="auto"
            )
            fig_cov.update_layout(title="Covariance Heatmap")
            st.plotly_chart(fig_cov, use_container_width=True)
            
            analysis_results = analyze_covariance_for_optimization(covariance_matrix, returns_data)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Condition Number", f"{analysis_results['condition_number']:.2f}")
            with col2:
                st.metric("Min Correlation", f"{analysis_results['min_correlation']:.2f}")
            with col3:
                st.metric("Max Correlation", f"{analysis_results['max_correlation']:.2f}")
        
        st.session_state.returns_data = returns_data
        st.session_state.closing_prices = closing_prices
        st.session_state.covariance_matrix = covariance_matrix
        st.session_state.trading_days_metrics = trading_metrics
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            formatted_returns.to_excel(writer, sheet_name='Daily Returns')
            closing_prices.to_excel(writer, sheet_name='Closing Prices')
            returns_stats.to_excel(writer, sheet_name='Returns Statistics')
            correlation_matrix.to_excel(writer, sheet_name='Correlation Matrix')
            covariance_matrix.to_excel(writer, sheet_name='Covariance Matrix')
        
        st.download_button(
            label="Download Returns Analysis",
            data=output.getvalue(),
            file_name="returns_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        if st.button("Proceed to Portfolio Optimization"):
            st.session_state.step = 6
            st.rerun()
        
    except Exception as e:
        st.error(f"Error during returns analysis: {str(e)}")
        st.write("Detailed error information:", str(e))

def handle_portfolio_optimization():
    """Handle the portfolio optimization step"""
    if 'returns_data' not in st.session_state or 'covariance_matrix' not in st.session_state:
        st.warning("Please complete the returns analysis step first.")
        if st.button("Return to Returns Analysis"):
            st.session_state.step = 5
            st.rerun()
        return
    
    st.header("Step 6: Portfolio Optimization")
    
    returns_data = st.session_state.returns_data
    covariance_matrix = st.session_state.covariance_matrix
    selected_stocks = st.session_state.selected_stocks
    trading_days = st.session_state.trading_days_metrics['total_trading_days']
    
    mean_returns = returns_data.mean() * trading_days
    
    st.subheader("Optimization Parameters")
    
    objective = st.selectbox(
        "Select Optimization Objective",
        ["Maximize Sharpe Ratio", "Maximize Returns", "Minimize Volatility"],
        help="Choose the objective for portfolio optimization"
    )
    
    risk_free_rate = st.number_input(
        "Risk-free Rate (%)",
        value=7.0,
        min_value=0.0,
        max_value=20.0,
        help="Annual risk-free rate (default: 7%)"
    ) / 100
    
    st.subheader("Portfolio Constraints")
    
    max_stock_weight = st.number_input(
        "Maximum Weight per Stock (%)",
        value=100.0,
        min_value=0.0,
        max_value=100.0,
        help="Enter 100 for no limit. Example: 20 means no stock can exceed 20% weight"
    ) / 100
    
    st.subheader("Industry Weight Constraints")
    
    use_global_industry_limit = st.checkbox(
        "Use global industry limit?", 
        value=True,
        help="If checked, applies the same maximum weight limit to all industries"
    )
    
    industries = selected_stocks['Industry'].unique()
    
    if use_global_industry_limit:
        global_industry_limit = st.number_input(
            "Maximum weight per industry (%)",
            value=20.0,
            min_value=0.0,
            max_value=100.0,
            help="No industry can exceed this weight limit"
        ) / 100
        industry_limits = {industry: global_industry_limit for industry in industries}
    else:
        industry_limits = {}
        with st.expander("Individual Industry Weight Constraints"):
            st.write("Set maximum weight for each industry (100 for no limit)")
            current_industry_weights = selected_stocks.groupby('Industry').size() / len(selected_stocks) * 100
            
            for industry in industries:
                current_weight = current_industry_weights.get(industry, 0)
                industry_limits[industry] = st.number_input(
                    f"Max weight for {industry} (%)",
                    value=100.0,
                    min_value=0.0,
                    max_value=100.0,
                    help=f"Current exposure: {current_weight:.1f}%"
                ) / 100
    
    st.subheader("Market Cap Constraints")
    
    market_cap_counts = selected_stocks['Market Cap Category'].value_counts()
    market_cap_dist = (market_cap_counts / len(selected_stocks) * 100).round(2)
    
    market_cap_info = pd.DataFrame({
        'Number of Stocks': market_cap_counts,
        'Current Weight (%)': market_cap_dist,
        'Available for Optimization': ['Yes' if count > 0 else 'No' for count in market_cap_counts]
    })
    
    st.write("Current Market Cap Distribution:")
    st.dataframe(market_cap_info)
    
    st.write("Set Market Cap Weight Constraints:")
    cap_limits = {}
    col1, col2, col3 = st.columns(3)
    
    with col1:
        large_cap_available = market_cap_dist.get('Large-Cap', 0) > 0
        if large_cap_available:
            cap_limits['Large-Cap'] = st.number_input(
                "Max Large-Cap Weight (%)",
                value=min(100.0, float(market_cap_dist.get('Large-Cap', 100))),
                max_value=float(market_cap_dist.get('Large-Cap', 100)),
                help=f"Maximum available weight: {market_cap_dist.get('Large-Cap', 0):.1f}%"
            ) / 100
        else:
            st.write("Large-Cap Stocks")
            st.write("⚠️ No Large-Cap stocks available")
            cap_limits['Large-Cap'] = 0
    
    with col2:
        mid_cap_available = market_cap_dist.get('Mid-Cap', 0) > 0
        if mid_cap_available:
            cap_limits['Mid-Cap'] = st.number_input(
                "Max Mid-Cap Weight (%)",
                value=min(100.0, float(market_cap_dist.get('Mid-Cap', 100))),
                max_value=float(market_cap_dist.get('Mid-Cap', 100)),
                help=f"Maximum available weight: {market_cap_dist.get('Mid-Cap', 0):.1f}%"
            ) / 100
        else:
            st.write("Mid-Cap Stocks")
            st.write("⚠️ No Mid-Cap stocks available")
            cap_limits['Mid-Cap'] = 0
    
    with col3:
        small_cap_available = market_cap_dist.get('Small-Cap', 0) > 0
        if small_cap_available:
            cap_limits['Small-Cap'] = st.number_input(
                "Max Small-Cap Weight (%)",
                value=min(100.0, float(market_cap_dist.get('Small-Cap', 100))),
                max_value=float(market_cap_dist.get('Small-Cap', 100)),
                help=f"Maximum available weight: {market_cap_dist.get('Small-Cap', 0):.1f}%"
            ) / 100
        else:
            st.write("Small-Cap Stocks")
            st.write("⚠️ No Small-Cap stocks available")
            cap_limits['Small-Cap'] = 0
    
    if st.button("Run Portfolio Optimization"):
        try:
            with st.spinner("Optimizing portfolio..."):
                n_assets = len(returns_data.columns)
                initial_weights = np.array([1/n_assets] * n_assets)
                
                constraints = [
                    {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}
                ]
                
                bounds = tuple((0, max_stock_weight) for _ in range(n_assets))
                
                for industry in industries:
                    industry_stocks = selected_stocks[selected_stocks['Industry'] == industry]['Symbol'].values
                    industry_indices = [i for i, symbol in enumerate(returns_data.columns) if symbol in industry_stocks]
                    
                    if industry_indices:
                        constraints.append({
                            'type': 'ineq',
                            'fun': lambda x, idx=industry_indices: industry_limits[industry] - np.sum(x[idx])
                        })
                
                for cap_type in ['Large-Cap', 'Mid-Cap', 'Small-Cap']:
                    cap_stocks = selected_stocks[selected_stocks['Market Cap Category'] == cap_type]['Symbol'].values
                    cap_indices = [i for i, symbol in enumerate(returns_data.columns) if symbol in cap_stocks]
                    
                    if cap_indices:
                        constraints.append({
                            'type': 'ineq',
                            'fun': lambda x, idx=cap_indices: cap_limits[cap_type] - np.sum(x[idx])
                        })
                
                def portfolio_return(weights):
                    return np.sum(mean_returns * weights)
                
                def portfolio_volatility(weights):
                    return np.sqrt(np.dot(weights.T, np.dot(covariance_matrix, weights)))
                
                def sharpe_ratio(weights):
                    ret = portfolio_return(weights)
                    vol = portfolio_volatility(weights)
                    return (ret - risk_free_rate) / vol
                
                if objective == "Maximize Sharpe Ratio":
                    objective_function = lambda x: -sharpe_ratio(x)
                elif objective == "Maximize Returns":
                    objective_function = lambda x: -portfolio_return(x)
                else:
                    objective_function = portfolio_volatility
                
                result = minimize(
                    objective_function,
                    initial_weights,
                    method='SLSQP',
                    bounds=bounds,
                    constraints=constraints
                )
                
                if result.success:
                    optimal_weights = result.x / np.sum(result.x)
                    stock_info = selected_stocks.set_index('Symbol')
                    
                    # Calculate weights ensuring sum is exactly 100%
                    weights_pct = (optimal_weights * 100).round(2)
                    # Adjust the largest weight to make sum exactly 100%
                    weights_pct[np.argmax(weights_pct)] += 100 - weights_pct.sum()
                    
                    # Create DataFrame with explicit types
                    portfolio_results = pd.DataFrame({
                        'Stock': pd.Series([stock_info.loc[symbol, 'Stock'] for symbol in returns_data.columns], dtype=str),
                        'Ticker': pd.Series(returns_data.columns, dtype=str),
                        'Weight in %': pd.Series(weights_pct, dtype='float64'),
                        'Segment': pd.Series([stock_info.loc[symbol, 'Industry'] for symbol in returns_data.columns], dtype=str),
                        'Market Cap Category': pd.Series([stock_info.loc[symbol, 'Market Cap Category'] for symbol in returns_data.columns], dtype=str)
                    }).astype({
                        'Stock': 'string[python]',
                        'Ticker': 'string[python]',
                        'Weight in %': 'float64',
                        'Segment': 'string[python]',
                        'Market Cap Category': 'string[python]'
                    })
                    
                    # Filter and sort
                    portfolio_results = portfolio_results[portfolio_results['Weight in %'] > 0.01].copy()
                    portfolio_results = portfolio_results.sort_values('Weight in %', ascending=False)
                    
                    # Add total row with exact 100%
                    total_row = pd.DataFrame({
                        'Stock': pd.Series(['Total'], dtype='string[python]'),
                        'Ticker': pd.Series([''], dtype='string[python]'),
                        'Weight in %': pd.Series([100.00], dtype='float64'),
                        'Segment': pd.Series([''], dtype='string[python]'),
                        'Market Cap Category': pd.Series([''], dtype='string[python]')
                    })
                    
                    portfolio_results = pd.concat([portfolio_results, total_row], ignore_index=True)
                    
                    # Calculate metrics with normalized weights
                    final_weights = optimal_weights[optimal_weights > 0.01]
                    portfolio_ret = portfolio_return(optimal_weights)
                    portfolio_vol = portfolio_volatility(optimal_weights)
                    portfolio_sharpe = sharpe_ratio(optimal_weights)
                    
                    st.success("Portfolio optimization completed successfully!")
                    
                    # Display results
                    st.subheader("Portfolio Performance Metrics")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Stocks", len(portfolio_results)-1)
                    with col2:
                        st.metric("Annual Returns", f"{portfolio_ret*100:.2f}%")
                    with col3:
                        st.metric("Annual Volatility", f"{portfolio_vol*100:.2f}%")
                    with col4:
                        st.metric("Sharpe Ratio", f"{portfolio_sharpe:.2f}")
                    
                    st.subheader(f"Optimized Portfolio ({objective})")
                    st.dataframe(portfolio_results)

                    # Summary statistics
                    st.subheader("Portfolio Summary")
                    
                    # Market Cap summary
                    cap_summary = portfolio_results[:-1].groupby('Market Cap Category')['Weight in %'].agg(['sum', 'count']).round(2)
                    cap_summary.columns = ['Total Weight (%)', 'Number of Stocks']
                    st.write("Market Cap Distribution:")
                    st.dataframe(cap_summary)
                    
                    # Industry summary
                    industry_summary = portfolio_results[:-1].groupby('Segment')['Weight in %'].agg(['sum', 'count']).round(2)
                    industry_summary.columns = ['Total Weight (%)', 'Number of Stocks']
                    st.write("Industry Distribution:")
                    st.dataframe(industry_summary)

                    # Excel output
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        # Portfolio sheet
                        portfolio_results.to_excel(
                            writer, 
                            sheet_name='Portfolio',
                            index=False
                        )
                        
                        # Metrics sheet
                        metrics_df = pd.DataFrame({
                            'Metric': [
                                'Total Stocks',
                                'Annual Returns (%)',
                                'Annual Volatility (%)',
                                'Sharpe Ratio',
                                'Risk-free Rate (%)'
                            ],
                            'Value': [
                                len(portfolio_results)-1,
                                f"{portfolio_ret*100:.2f}",
                                f"{portfolio_vol*100:.2f}",
                                f"{portfolio_sharpe:.2f}",
                                f"{risk_free_rate*100:.2f}"
                            ]
                        })
                        metrics_df.to_excel(
                            writer,
                            sheet_name='Portfolio Metrics',
                            index=False
                        )
                        
                        # Market Cap Distribution
                        cap_summary.to_excel(
                            writer,
                            sheet_name='Market Cap Dist',
                            index=True
                        )
                        
                        # Industry Distribution
                        industry_summary.to_excel(
                            writer,
                            sheet_name='Industry Dist',
                            index=True
                        )
                        
                        # Optimization Parameters
                        params_df = pd.DataFrame({
                            'Parameter': [
                                'Optimization Objective',
                                'Risk-free Rate (%)',
                                'Max Stock Weight (%)',
                                'Max Large-Cap Weight (%)',
                                'Max Mid-Cap Weight (%)',
                                'Max Small-Cap Weight (%)'
                            ],
                            'Value': [
                                objective,
                                f"{risk_free_rate*100:.1f}",
                                f"{max_stock_weight*100:.1f}",
                                f"{cap_limits['Large-Cap']*100:.1f}",
                                f"{cap_limits['Mid-Cap']*100:.1f}",
                                f"{cap_limits['Small-Cap']*100:.1f}"
                            ]
                        })
                        params_df.to_excel(
                            writer,
                            sheet_name='Parameters',
                            index=False
                        )
                    
                    st.download_button(
                        label="Download Portfolio Results",
                        data=output.getvalue(),
                        file_name=f"portfolio_optimization.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                else:
                    st.error("Optimization failed. Please try adjusting your constraints.")
                    st.write("Optimization Error:", result.message)
        
        except Exception as e:
            st.error("Error during portfolio optimization:")
            st.error(str(e))

def main():
    st.set_page_config(page_title="Portfolio Optimizer", layout="wide")
    initialize_session_state()
    
    st.title("Portfolio Optimization Tool")
    
    with st.sidebar:
        st.header("Navigation")
        steps = [
            "1. Data Import & Cleaning",
            "2. Data Normalization",
            "3. Composite Score",
            "4. Stock Selection",
            "5. Returns Analysis",
            "6. Portfolio Optimization"
        ]
        selected_step = st.radio("Steps:", steps, index=st.session_state.step - 1)
        st.session_state.step = steps.index(selected_step) + 1

    if st.session_state.step == 1:
        handle_data_import()
    elif st.session_state.step == 2:
        handle_normalization()
    elif st.session_state.step == 3:
        handle_composite_score()
    elif st.session_state.step == 4:
        handle_stock_selection()
    elif st.session_state.step == 5:
        handle_returns_analysis()
    elif st.session_state.step == 6:
        handle_portfolio_optimization()

if __name__ == "__main__":
    main()