import numpy as np
import ants
from scipy.fft import fftn, ifftn, fftshift, ifftshift
import warnings

class DegradationSimulator:
    """
    A physics-based MRI degradation simulator for generating low-resolution
    anisotropic scans from high-resolution isotropic volumes.
    
    This class prioritizes realistic MRI physics models over computer vision approximations:
    1. Slice Thickness: Simulated via Slab Integration (Boxcar Averaging) rather 
       than Gaussian blurring. This models the Partial Volume Effect (PVE) by 
       summing spin magnetization over the slice width.
    2. In-plane Resolution: Simulated via K-space truncation (simulating finite 
       matrix size) to induce realistic Gibbs ringing, rather than smooth Gaussian blur.
    3. Inter-slice Gaps: Simulated via spatial skipping of anatomical data, 
       modeling the loss of tissue information between excitation slabs.
    
    Attributes:
        image (ants.core.ants_image.ANTsImage): The input high-resolution image.
        hr_spacing (tuple): Original voxel spacing (mm).
        hr_origin (tuple): Original physical origin (mm).
        hr_direction (numpy.ndarray): Direction cosine matrix.
    """

    def __init__(self, image_path_or_object):
        """
        Initialize the simulator with an ANTsImage or path to NIfTI.
        
        Args:
            image_path_or_object: File path (str) or ants.ANTsImage object.
        """
        if isinstance(image_path_or_object, str):
            self.image = ants.image_read(image_path_or_object)
        elif isinstance(image_path_or_object, ants.core.ants_image.ANTsImage):
            self.image = image_path_or_object
        else:
            raise ValueError("Input must be a path string or ANTsImage object.")
        
        self.hr_spacing = self.image.spacing
        self.hr_origin = self.image.origin
        self.hr_direction = self.image.direction

    def _calculate_new_origin(self, slice_axis, voxels_per_slice):
        """
        Calculates the new physical origin after slice thickening.
        When multiple slices are averaged, the effective center of the new 
        thick slice shifts relative to the first HR slice.
        
        Shift = (N - 1) * spacing / 2
        
        Args:
            slice_axis (int): The axis of degradation.
            voxels_per_slice (int): The downsampling factor.
            
        Returns:
            tuple: The new origin coordinates.
        """
        current_spacing = self.hr_spacing[slice_axis]
        shift_mm = (voxels_per_slice - 1) * current_spacing / 2.0
        
        # Create offset vector in voxel space (e.g., [0, 0, shift])
        offset_vector = np.zeros(self.image.dimension)
        offset_vector[slice_axis] = shift_mm
        
        # Rotate offset by direction matrix to get physical space shift
        direction_mat = np.array(self.hr_direction).reshape(self.image.dimension, self.image.dimension)
        physical_shift = direction_mat @ offset_vector
        
        new_origin = np.array(self.hr_origin) + physical_shift
        return tuple(new_origin)

    def simulate_thick_slices(self, thickness_mm, slice_axis=2):
        """
        Simulates thick MRI slices by integrating (averaging) signal over the 
        slice thickness. This models the Partial Volume Effect (PVE) accurately 
        by treating the voxel value as the sum of spins in the slab.
        
        This replaces the unrealistic Gaussian blur approach found in general 
        computer vision SISR.
        
        Args:
            thickness_mm (float): Target slice thickness in millimeters.
            slice_axis (int): Axis along which to thicken (0=Sagittal, 1=Coronal, 2=Axial).
                              Default is 2 (Axial z-axis).
                              
        Returns:
            ants.ANTsImage: The simulated thick-slice image (anisotropic).
        """
        current_spacing = self.hr_spacing[slice_axis]
        factor = thickness_mm / current_spacing
        
        # Strict physics simulation requires integer integration steps for 
        # perfect boxcar profile. If non-integer, we round to nearest.
        int_factor = int(round(factor))
        
        if int_factor < 1:
            raise ValueError("Target thickness cannot be smaller than input resolution.")
        if int_factor == 1:
            warnings.warn("Target thickness equals input resolution. No degradation applied.")
            return self.image
        
        data = self.image.numpy()
        
        # Handle geometric truncation: The volume might not be perfectly divisible 
        # by the new thickness. We crop the end to fit integer blocks.
        dim_size = data.shape[slice_axis]
        new_dim_size = dim_size // int_factor
        cutoff = new_dim_size * int_factor
        
        # Create slice object to crop data
        sl = [slice(None)] * data.ndim
        sl[slice_axis] = slice(0, cutoff)
        data_cropped = data[tuple(sl)]
        
        # Vectorized Block Averaging
        # 1. Move the target axis to the last dimension for easier reshaping
        data_swapped = np.moveaxis(data_cropped, slice_axis, -1)
        
        # 2. Reshape (..., Total_Z) -> (..., New_Z, Factor)
        temp_shape = list(data_swapped.shape[:-1]) + [new_dim_size, int_factor]
        data_reshaped = data_swapped.reshape(temp_shape)
        
        # 3. Mean over the Factor dimension (Axis -1)
        # This simulates the coil integrating signal from the entire slab.
        data_thick = data_reshaped.mean(axis=-1)
        
        # 4. Move axis back to original position
        data_final = np.moveaxis(data_thick, -1, slice_axis)
        
        # Update Metadata
        new_spacing = list(self.hr_spacing)
        new_spacing[slice_axis] = current_spacing * int_factor
        
        new_origin = self._calculate_new_origin(slice_axis, int_factor)
        
        return ants.from_numpy(
            data_final,
            origin=new_origin,
            spacing=tuple(new_spacing),
            direction=self.hr_direction
        )

    def simulate_inter_slice_gap(self, thickness_mm, gap_mm, slice_axis=2):
        """
        Simulates an acquisition with both thick slices and inter-slice gaps.
        
        Physics: The scanner acquires a slab of 'thickness_mm', then mechanically
        or electrically skips 'gap_mm' before the next acquisition to prevent 
        cross-talk. This results in permanent data loss in the gap regions.
        
        Args:
            thickness_mm (float): The thickness of the acquired slab.
            gap_mm (float): The empty space between acquired slabs.
            slice_axis (int): Axis of degradation.
            
        Returns:
            ants.ANTsImage: The sparse, thick-slice image with corrected spacing.
        """
        current_spacing = self.hr_spacing[slice_axis]
        
        # Calculate voxel counts for slice and gap
        voxels_per_slice = int(round(thickness_mm / current_spacing))
        voxels_gap = int(round(gap_mm / current_spacing))
        stride = voxels_per_slice + voxels_gap
        
        if voxels_per_slice < 1:
            raise ValueError("Slice thickness smaller than input resolution.")
            
        data = self.image.numpy()
        dim_size = data.shape[slice_axis]
        
        indices = []
        # Strided Loop: Simulate the acquisition stepping through the volume
        for start_idx in range(0, dim_size, stride):
            end_idx = start_idx + voxels_per_slice
            if end_idx <= dim_size:
                # Extract the slab
                sl = [slice(None)] * data.ndim
                sl[slice_axis] = slice(start_idx, end_idx)
                slab = data[tuple(sl)]
                
                # Integrate (Average) signal in slab -> collapse to 1 slice
                # keepdims=True maintains 3D structure for concatenation
                slab_integrated = slab.mean(axis=slice_axis, keepdims=True)
                indices.append(slab_integrated)
        
        if not indices:
            raise ValueError("Gap/Thickness settings resulted in no slices (Volume too small).")
            
        # Concatenate the acquired slices back into a volume
        data_gapped = np.concatenate(indices, axis=slice_axis)
        
        # Update Metadata
        # Spacing in dicom/nifti is center-to-center distance.
        # Center-to-center = Thickness + Gap
        new_z_spacing = thickness_mm + gap_mm
        new_spacing = list(self.hr_spacing)
        new_spacing[slice_axis] = new_z_spacing
        
        new_origin = self._calculate_new_origin(slice_axis, voxels_per_slice)

        return ants.from_numpy(
            data_gapped,
            origin=new_origin,
            spacing=tuple(new_spacing),
            direction=self.hr_direction
        )

    def simulate_in_plane_resolution(self, downsample_factor):
        """
        Simulates in-plane resolution reduction via K-space truncation.
        This reproduces Gibbs ringing artifacts associated with low-matrix acquisitions.
        
        Args:
            downsample_factor (int): Factor by which to reduce resolution (e.g., 2).
                                     Applied to the two non-slice axes.
        """
        # Identify in-plane axes (assuming z=2 is slice axis for simplicity, 
        # though this can be generalized)
        # For this example, we apply to all axes or specify dimensions.
        # Let's assume isotropic downsampling for this method demonstration.
        
        data = self.image.numpy()
        
        # 1. FFT to K-space
        # fftshift moves zero-frequency component to center of spectrum
        kspace = fftshift(fftn(data))
        
        # 2. Determine Crop Window (Truncation)
        center = np.array(kspace.shape) // 2
        new_dims = np.array(kspace.shape) // downsample_factor
        new_dims = new_dims.astype(int)
        
        start = center - new_dims // 2
        end = start + new_dims
        
        # Crop the high frequencies
        sl = tuple(slice(s, e) for s, e in zip(start, end))
        kspace_cropped = kspace[sl]
        
        # 3. Inverse FFT
        # ifftshift moves zero-frequency back to corner before IFFT
        img_lr_complex = ifftn(ifftshift(kspace_cropped))
        img_lr = np.abs(img_lr_complex) # Magnitude reconstruction
        
        # 4. Update Metadata
        new_spacing = [s * downsample_factor for s in self.hr_spacing]
        
        # Note: K-space truncation implicitly centers the field of view, 
        # but origin handling can be subtle depending on phase encoding centers.
        # We assume standard centered reconstruction here.
        
        return ants.from_numpy(
            img_lr,
            origin=self.hr_origin,
            spacing=tuple(new_spacing),
            direction=self.hr_direction
        )