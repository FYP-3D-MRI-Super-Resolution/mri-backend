import numpy as np
import matplotlib.pyplot as plt
import nibabel as nib
import ants
from pathlib import Path


def show_mri_histogram(input_file, bins=100, title=None, save_path=None, figsize=(12, 6)):
    """
    Load an MRI scan (.nii.gz file) and display its intensity distribution as a histogram.
    
    Args:
        input_file (str or Path): Path to the .nii.gz MRI file
        bins (int): Number of bins for the histogram (default: 100)
        title (str, optional): Custom title for the plot. If None, uses filename
        save_path (str or Path, optional): Path to save the histogram image. If None, displays only
        figsize (tuple): Figure size (width, height) in inches (default: (12, 6))
    
    Returns:
        dict: Dictionary containing statistics:
            - 'mean': Mean intensity
            - 'std': Standard deviation
            - 'min': Minimum intensity
            - 'max': Maximum intensity
            - 'median': Median intensity
            - 'data': Flattened array of voxel intensities
    
    Example:
        >>> stats = show_mri_histogram('path/to/scan.nii.gz', bins=50)
        >>> print(f"Mean intensity: {stats['mean']:.2f}")
    """
    # Load the MRI scan
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_file}")
    
    print(f"Loading MRI scan: {input_path.name}")
    
    # Load using nibabel for universal compatibility
    nii_img = nib.load(str(input_path))
    data = nii_img.get_fdata()
    
    # Flatten the 3D volume to 1D array
    data_flat = data.flatten()
    
    # Remove zero/background voxels for better visualization
    # (many MRI scans have large background regions with zero intensity)
    non_zero_data = data_flat[data_flat > 0]
    
    # Calculate statistics
    stats = {
        'mean': np.mean(non_zero_data),
        'std': np.std(non_zero_data),
        'min': np.min(non_zero_data),
        'max': np.max(non_zero_data),
        'median': np.median(non_zero_data),
        'data': non_zero_data,
        'total_voxels': len(data_flat),
        'non_zero_voxels': len(non_zero_data)
    }
    
    # Create the histogram
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
    
    # Plot 1: Histogram with all non-zero intensities
    ax1.hist(non_zero_data, bins=bins, color='steelblue', alpha=0.7, edgecolor='black')
    ax1.axvline(stats['mean'], color='red', linestyle='--', linewidth=2, label=f"Mean: {stats['mean']:.2f}")
    ax1.axvline(stats['median'], color='green', linestyle='--', linewidth=2, label=f"Median: {stats['median']:.2f}")
    ax1.set_xlabel('Intensity Value', fontsize=12)
    ax1.set_ylabel('Frequency (Number of Voxels)', fontsize=12)
    ax1.set_title('Intensity Distribution (Non-Zero Voxels)', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Box plot for distribution overview
    ax2.boxplot(non_zero_data, vert=True, patch_artist=True,
                boxprops=dict(facecolor='lightblue', alpha=0.7),
                medianprops=dict(color='red', linewidth=2))
    ax2.set_ylabel('Intensity Value', fontsize=12)
    ax2.set_title('Box Plot', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Overall title
    if title is None:
        title = f"MRI Intensity Distribution: {input_path.name}"
    fig.suptitle(title, fontsize=16, fontweight='bold', y=1.00)
    
    # Add statistics text
    stats_text = (
        f"Statistics (Non-Zero Voxels):\n"
        f"Mean: {stats['mean']:.2f}\n"
        f"Std: {stats['std']:.2f}\n"
        f"Min: {stats['min']:.2f}\n"
        f"Max: {stats['max']:.2f}\n"
        f"Median: {stats['median']:.2f}\n"
        f"Total Voxels: {stats['total_voxels']:,}\n"
        f"Non-Zero: {stats['non_zero_voxels']:,}"
    )
    fig.text(0.98, 0.5, stats_text, fontsize=10, verticalalignment='center',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
             family='monospace')
    
    plt.tight_layout()
    
    # Save or display
    if save_path:
        save_path = Path(save_path)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Histogram saved to: {save_path}")
    
    plt.show()
    
    # Print statistics to console
    print("\n" + "="*50)
    print("MRI INTENSITY STATISTICS (Non-Zero Voxels)")
    print("="*50)
    print(f"Mean:          {stats['mean']:.4f}")
    print(f"Std Dev:       {stats['std']:.4f}")
    print(f"Minimum:       {stats['min']:.4f}")
    print(f"Maximum:       {stats['max']:.4f}")
    print(f"Median:        {stats['median']:.4f}")
    print(f"Total Voxels:  {stats['total_voxels']:,}")
    print(f"Non-Zero:      {stats['non_zero_voxels']:,}")
    print(f"Percentage:    {(stats['non_zero_voxels']/stats['total_voxels']*100):.2f}%")
    print("="*50 + "\n")
    
    return stats


def compare_mri_histograms(file_list, labels=None, bins=100, title="MRI Comparison", save_path=None):
    """
    Compare intensity distributions of multiple MRI scans in a single plot.
    
    Args:
        file_list (list): List of paths to .nii.gz MRI files
        labels (list, optional): Labels for each file. If None, uses filenames
        bins (int): Number of bins for the histogram (default: 100)
        title (str): Title for the comparison plot
        save_path (str or Path, optional): Path to save the comparison image
    
    Returns:
        dict: Dictionary with statistics for each file
    
    Example:
        >>> files = ['scan1.nii.gz', 'scan2.nii.gz']
        >>> stats = compare_mri_histograms(files, labels=['Before', 'After'])
    """
    if labels is None:
        labels = [Path(f).name for f in file_list]
    
    fig, ax = plt.subplots(figsize=(14, 8))
    all_stats = {}
    colors = plt.cm.tab10(np.linspace(0, 1, len(file_list)))
    
    for idx, (file_path, label) in enumerate(zip(file_list, labels)):
        # Load the MRI scan
        nii_img = nib.load(str(file_path))
        data = nii_img.get_fdata()
        data_flat = data.flatten()
        non_zero_data = data_flat[data_flat > 0]
        
        # Calculate statistics
        all_stats[label] = {
            'mean': np.mean(non_zero_data),
            'std': np.std(non_zero_data),
            'median': np.median(non_zero_data)
        }
        
        # Plot histogram
        ax.hist(non_zero_data, bins=bins, alpha=0.5, label=label, 
                color=colors[idx], edgecolor='black', linewidth=0.5)
    
    ax.set_xlabel('Intensity Value', fontsize=12)
    ax.set_ylabel('Frequency (Number of Voxels)', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Comparison histogram saved to: {save_path}")
    
    plt.show()
    
    return all_stats
